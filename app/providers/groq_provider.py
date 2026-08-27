class GroqProvider:
    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    def generate(self, message: str) -> str:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")

        from groq import Groq

        client = Groq(api_key=self.api_key)
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": message,
                }
            ],
        )

        content = completion.choices[0].message.content
        if content is None:
            raise RuntimeError("Groq returned an empty response")

        return str(content)
