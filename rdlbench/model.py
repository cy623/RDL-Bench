"""LLM wrapper — supports HuggingFace local models and Claude API."""

import os
import time
import random


class LLMWrapper:

    def __init__(self, model_name: str, device: str = "auto", api_key: str = "", quantization: str = None):
        self.model_name = model_name
        self._is_claude = model_name.startswith("claude-")

        if self._is_claude:
            self._init_claude(api_key)
        else:
            self._init_hf(model_name, device, quantization)

    # ── Claude (Anthropic API) ─────────────────────────────────────────────

    def _init_claude(self, api_key: str = ""):
        import anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise EnvironmentError(
                "No API key found. Set api_key in config.yaml or "
                "export ANTHROPIC_API_KEY=<your_key>"
            )
        # max_retries=10 with SDK-native exponential backoff for 529 overloaded
        self._client = anthropic.Anthropic(api_key=key, max_retries=10)
        print(f"[Model] Claude API ready: {self.model_name}")

    def _generate_claude(self, prompt: str, max_new_tokens: int,
                         temperature: float = 0.0) -> str:
        import anthropic
        kwargs = dict(
            model=self.model_name,
            max_tokens=max_new_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if temperature > 0:
            kwargs["temperature"] = temperature
        # Extra outer retry loop for persistent 529 overloaded errors
        for attempt in range(5):
            try:
                response = self._client.messages.create(**kwargs)
                return response.content[0].text.strip()
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < 4:
                    wait = 30 * (2 ** attempt) + random.uniform(0, 5)
                    print(f"[Claude] 529 overloaded, waiting {wait:.0f}s (attempt {attempt+1}/5)")
                    time.sleep(wait)
                else:
                    raise

    # ── HuggingFace local ──────────────────────────────────────────────────

    def _init_hf(self, model_name: str, device: str, quantization: str = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, pipeline

        print(f"[Model] Loading {model_name} (quantization={quantization}) ...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=True, local_files_only=True
        )

        bnb_config = None
        if quantization == "4bit":
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
        elif quantization == "8bit":
            bnb_config = BitsAndBytesConfig(load_in_8bit=True)

        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16 if not bnb_config else None,
            device_map=device,
            trust_remote_code=True,
            local_files_only=True,
            quantization_config=bnb_config,
        )
        self.pipe = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            do_sample=False,
            temperature=None,
            top_p=None,
        )
        print("[Model] Ready.")

    def _generate_hf(self, prompt: str, max_new_tokens: int,
                     temperature: float = 0.0) -> str:
        gen_kwargs = dict(max_new_tokens=max_new_tokens, return_full_text=False)
        if temperature > 0:
            gen_kwargs["do_sample"]   = True
            gen_kwargs["temperature"] = temperature
        else:
            gen_kwargs["do_sample"]   = False
            gen_kwargs["temperature"] = None
            gen_kwargs["top_p"]       = None
        out = self.pipe([{"role": "user", "content": prompt}], **gen_kwargs)
        return out[0]["generated_text"].strip()

    # ── Public interface ───────────────────────────────────────────────────

    def generate(self, prompt: str, max_new_tokens: int = 512,
                 temperature: float = 0.0) -> str:
        if self._is_claude:
            return self._generate_claude(prompt, max_new_tokens, temperature)
        return self._generate_hf(prompt, max_new_tokens, temperature)
