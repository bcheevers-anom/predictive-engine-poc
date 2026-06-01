# Skill: narrative

**Version:** v1  
**Model tier:** mid  
**Type:** LLM  
**Purpose:** Render a plain-language forecast reasoning message from a structured Finding object.

## Faithfulness requirement (TC-011)
Every claim in the narrative MUST be present in the structured Finding object.  
Reject and re-generate (once) if any claim is absent.

## Inputs
A `Finding` object (JSON)

## Outputs
`{"narrative": "<plain text>", "faithfulness_checked": true, "rejected_claims": []}`

## Prompt reference
`prompts/narrative_v1.txt`
