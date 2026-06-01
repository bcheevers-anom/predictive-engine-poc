import json
import os
from pathlib import Path
from typing import Any, Type

import boto3
import botocore.exceptions
import yaml
from pydantic import BaseModel

from pte.common.errors import AuthError, LLMError, RateLimitError
from pte.common.logging import structured_log
from pte.gateway.cost import CostTracker
from pte.gateway.rate_limit import TokenBucketLimiter


def _load_models() -> dict:
    path = Path(__file__).parents[3] / "config" / "models.yaml"
    with open(path) as f:
        return yaml.safe_load(f)

def _load_default_config() -> dict:
    path = Path(__file__).parents[3] / "config" / "default.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


class LLMClient:
    def __init__(self):
        cfg = _load_default_config()
        self._backend = os.environ.get("LLM_BACKEND", cfg["llm"]["backend"])
        self._models = _load_models()
        llm_cfg = cfg["llm"]

        if self._backend == "bedrock":
            bc = llm_cfg["bedrock"]
            self._limiter = TokenBucketLimiter(tpm_limit=bc["tpm_limit"], rpm_limit=bc["rpm_limit"])
            self._region = os.environ.get("AWS_REGION", bc["region"])
            self._profile = os.environ.get("AWS_PROFILE", bc["profile"])
        else:
            ac = llm_cfg["anthropic"]
            self._limiter = TokenBucketLimiter(tpm_limit=ac["tpm_limit"], rpm_limit=ac["rpm_limit"])

        self._trackers: dict[str, CostTracker] = {}

    def _model_id(self, tier: str) -> str:
        return self._models[self._backend][tier]

    def _get_tracker(self, model_id: str) -> CostTracker:
        if model_id not in self._trackers:
            self._trackers[model_id] = CostTracker(backend=self._backend, model_id=model_id)
        return self._trackers[model_id]

    async def complete(
        self,
        prompt: str,
        model_tier: str = "fast",
        schema: Type[BaseModel] | None = None,
        max_tokens: int = 4096,
    ) -> Any:
        model_id = self._model_id(model_tier)
        await self._limiter.acquire(input_tokens=len(prompt) // 4, output_tokens=max_tokens // 4)

        if self._backend == "bedrock":
            return await self._complete_bedrock(prompt, model_id, schema, max_tokens)
        return await self._complete_anthropic(prompt, model_id, schema, max_tokens)

    async def _complete_bedrock(self, prompt: str, model_id: str, schema, max_tokens: int) -> Any:
        try:
            session = boto3.Session(profile_name=self._profile, region_name=self._region)
            client = session.client("bedrock-runtime")
        except botocore.exceptions.NoCredentialsError:
            raise AuthError("bedrock")
        except botocore.exceptions.ProfileNotFound:
            raise AuthError("bedrock")

        messages = [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": max_tokens, "messages": messages}

        if schema:
            tool_def = {
                "name": "structured_output",
                "description": "Return structured data matching the schema.",
                "input_schema": schema.model_json_schema(),
            }
            body["tools"] = [tool_def]
            body["tool_choice"] = {"type": "tool", "name": "structured_output"}

        try:
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
        except botocore.exceptions.NoCredentialsError:
            raise AuthError("bedrock")
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("ThrottlingException", "TooManyRequestsException"):
                raise RateLimitError(backend="bedrock")
            if code in ("ExpiredTokenException", "InvalidSignatureException"):
                raise AuthError("bedrock")
            raise LLMError(str(e)) from e

        result = json.loads(response["body"].read())
        usage = result.get("usage", {})
        tracker = self._get_tracker(model_id)
        tracker.record(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

        if schema:
            for block in result.get("content", []):
                if block.get("type") == "tool_use":
                    return schema.model_validate(block["input"])
            raise LLMError("No tool_use block in Bedrock response")

        text = "".join(b.get("text", "") for b in result.get("content", []) if b.get("type") == "text")
        return text

    async def _complete_anthropic(self, prompt: str, model_id: str, schema, max_tokens: int) -> Any:
        import anthropic as _anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AuthError("anthropic")
        client = _anthropic.Anthropic(api_key=api_key)
        messages = [{"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {"model": model_id, "max_tokens": max_tokens, "messages": messages}
        if schema:
            tool_def = {
                "name": "structured_output",
                "description": "Return structured data.",
                "input_schema": schema.model_json_schema(),
            }
            kwargs["tools"] = [tool_def]
            kwargs["tool_choice"] = {"type": "tool", "name": "structured_output"}

        try:
            response = client.messages.create(**kwargs)
        except _anthropic.AuthenticationError:
            raise AuthError("anthropic")
        except _anthropic.RateLimitError:
            raise RateLimitError(backend="anthropic")

        tracker = self._get_tracker(model_id)
        tracker.record(input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)

        if schema:
            for block in response.content:
                if block.type == "tool_use":
                    return schema.model_validate(block.input)
            raise LLMError("No tool_use block in Anthropic response")

        return "".join(b.text for b in response.content if b.type == "text")

    def cost_summaries(self) -> list[dict]:
        return [t.summary() for t in self._trackers.values()]
