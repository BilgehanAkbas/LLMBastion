# LLMBastion Multilingual Prompt Injection Dataset v1

## Goal
Build a clean multilingual dataset for training and evaluating SemanticGuard v2 without contaminating external benchmarks.

## Target size
- Total: 1,200 prompts
- Attack: 600
- Safe: 600
- Languages: ~45% Turkish, ~45% English, ~10% Turkish-English mixed
- Split target: train 70%, validation 15%, locked_test 15%

## Attack families
15 families, target ~40 attack examples per family:

1. instruction_override
2. system_prompt_exfiltration
3. security_bypass
4. roleplay_jailbreak
5. authority_claim_bypass
6. memory_context_poisoning
7. rag_context_poisoning
8. indirect_injection
9. tool_action_abuse
10. sensitive_data_exfiltration
11. confirmation_trap
12. encoding_obfuscation
13. morphological_bypass
14. code_switching
15. social_engineering_escalation

## Safe distribution
- hard_negative: 300
- benign_daily: 120
- benign_technical: 100
- benign_security: 80

Hard negatives should contain security-sensitive words or structures but must NOT instruct the model to violate policy.
Roughly half of attack examples should have a paired safe hard-negative using the same scenario/topic.

## Required fields
- id
- text
- label
- language
- category
- attack_family
- difficulty
- obfuscation
- source
- source_id
- license
- pair_id
- split

## Label contract
attack:
The prompt attempts to override higher-priority instructions, extract hidden/system data, bypass safeguards, poison context/memory/RAG, abuse tools/actions, or exfiltrate protected information.

safe:
The prompt does not attempt those behaviors. Security discussion, quoting an attack, translating suspicious text without executing it, asking defensive questions, or discussing policies can still be safe.

## Difficulty
- easy: explicit attack wording
- medium: indirect/paraphrased attack
- hard: subtle contextual, role-based, obfuscated, or boundary attack

## Obfuscation
- none
- typo
- spacing
- punctuation
- leetspeak
- unicode
- homoglyph
- encoding
- mixed

## Leakage rules
- Never copy AltaySec benchmark prompts into training.
- Never copy current locked/external test examples into training.
- Near-paraphrases must stay in the same split.
- paired attack/safe examples must stay in the same split.
- source-derived variants from the same base prompt must stay in the same split.

## Quality rules
- No real credentials, API keys, personal data, phone numbers, IDs, or secrets.
- Synthetic placeholders only.
- Avoid trivial lexical shortcuts where one word alone predicts the label.
- Include safe examples containing words such as system, prompt, log, admin, token, secret, API, rule, güvenlik, yönetici, şifre, anahtar.
- Include attack examples that avoid obvious words such as ignore, jailbreak, system prompt.
- Turkish examples must read naturally; do not create machine-translated Turkish only.
- English and Turkish examples should cover equivalent concepts without being direct translations of every row.

## Split policy
The locked test is created once and must not be used to tune:
- model hyperparameters
- threshold
- preprocessing
- feature representation
- attack-family weighting

Only train + validation may be used during development.
