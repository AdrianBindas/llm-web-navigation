from __future__ import annotations

import torch
from transformers import AutoModelForImageTextToText, AutoProcessor, GenerationConfig
from qwen_vl_utils import process_vision_info

SCREENSHOT_PATH = "images/screenshot_booking.png"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

MIN_PIXELS = 256 * 28 * 28
MAX_PIXELS = 512 * 28 * 28

DESCRIPTION_SYSTEM_PROMPT = (
    "# List the elements visible in the screenshot using markdown bullet points. "
    "Describe each elements with a short sentence.\n"
    "# Do NOT output anything else except the list of elements."
)


def build_messages(image_path: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": DESCRIPTION_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {"type": "image", "image": f"file://{image_path}"},
            ],
        },
    ]


def generate_reasoning(
    model,
    processor,
    messages: list[dict],
    max_new_tokens: int = 512,
    temperature: float = 0.7,
    top_p: float = 0.9,
) -> str:
    text_prompt = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, _ = process_vision_info(messages)

    inputs = processor(
        text=[text_prompt],
        images=image_inputs,
        return_tensors="pt",
    )
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

    gen_config = GenerationConfig(
        max_new_tokens=max_new_tokens,
        do_sample=temperature > 0.0,
        temperature=temperature,
        top_p=top_p,
        pad_token_id=processor.tokenizer.pad_token_id,
        eos_token_id=processor.tokenizer.eos_token_id,
        length_penalty=-0.2,
    )

    with torch.inference_mode():
        output_ids = model.generate(**inputs, generation_config=gen_config)

    prompt_len = inputs["input_ids"].shape[1]
    reasoning = processor.batch_decode(
        output_ids[:, prompt_len:],
        skip_special_tokens=True,
        clean_up_tokenization_spaces=True,
    )[0]
    return reasoning.strip()


def run(
    model_name: str,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.9,
) -> None:
    print(f"Loading model: {model_name}")
    processor = AutoProcessor.from_pretrained(
        model_name, min_pixels=MIN_PIXELS, max_pixels=MAX_PIXELS
    )
    model = AutoModelForImageTextToText.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    ).to(DEVICE)
    model.eval()

    messages = build_messages(SCREENSHOT_PATH)

    try:
        description = generate_reasoning(
            model, processor, messages, max_new_tokens, temperature, top_p
        )
    except Exception as exc:
        description = f"ERROR: {exc}"
    print(description)


if __name__ == "__main__":
    run(
        model_name="Qwen/Qwen3.5-2B",
        max_new_tokens=512,
        temperature=0.7,
        top_p=0.9,
    )