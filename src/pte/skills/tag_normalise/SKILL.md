# Skill: tag_normalise

**Version:** v1  
**Model tier:** fast (small LLM fallback only)  
**Type:** deterministic + small LLM fallback  
**Purpose:** Canonicalise family/tool/tactic tag dialects across feeds; exclude workflow tags.

## Process
1. Look up tag in `alias_map.py`
2. If found: return canonical form
3. If not found: attempt small LLM to propose a canonical mapping
4. If still unmapped: return to "unmapped" bucket — **never drop**

## Prompt reference
`prompts/tag_normalise_v1.txt`
