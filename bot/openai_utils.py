import base64
from io import BytesIO
import config
import logging

import tiktoken
import openai
import anthropic
import logging

import json #logging error

#from tokenizers import Tokenizer, models, pre_tokenizers, trainers # other tokenizer module

# setup openai
openai.api_key = config.openai_api_key
anthropic.api_key = config.anthropic_api_key

if config.openai_api_base is not None:
    openai.api_base = config.openai_api_base

OPENAI_COMPLETION_OPTIONS = {
    "temperature": 0.7,
    "max_tokens": 1000,
    "top_p": 1,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "request_timeout": 60.0,
}

logger = logging.getLogger(__name__)

def configure_logging():
    # Configure logging based on the enable_detailed_logging value
    if config.enable_detailed_logging:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    else:
        logging.basicConfig(level=logging.CRITICAL, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # Set the logger level based on configuration
    logger.setLevel(logging.getLogger().level)

configure_logging()

def validate_payload(payload): #maybe comment out
    # Example validation: Ensure all messages have content that is a string
    for message in payload.get("messages", []):
        if not isinstance(message.get("content"), str):
            logger.error("Invalid message content: Not a string")
            raise ValueError("Message content must be a string")

        
class ChatGPT:
    def __init__(self, model="gpt-4-1106-preview"):
        assert model in {"text-davinci-003", "gpt-3.5-turbo-16k", "gpt-3.5-turbo", "gpt-4", "gpt-4-1106-preview", "gpt-4-vision-preview", "gpt-4-turbo-2024-04-09", "gpt-4o", "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"}, f"Unknown model: {model}"
        self.model = model
        self.is_claude_model = model.startswith("claude")
        self.logger = logging.getLogger(__name__)
        self.headers = {
            "Authorization": f"Bearer {config.anthropic_api_key if self.is_claude_model else config.openai_api_key}",
            "Content-Type": "application/json",
        }

    async def send_message(self, message, dialog_messages=[], chat_mode="assistant"):
        if chat_mode not in config.chat_modes.keys():
            raise ValueError(f"Chat mode {chat_mode} is not supported")

        n_dialog_messages_before = len(dialog_messages)
        answer = None
        while answer is None:
            try:
                if self.is_claude_model:
                    prompt = self._generate_claude_prompt(message, dialog_messages, chat_mode)
                    self.logger.debug(f"Claude prompt: {prompt}")

                    if not prompt.strip():
                        raise ValueError("Generated prompt is empty")

                    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
                    response = await client.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=1000,
                        temperature=0.7
                    )
                    self.logger.debug(f"Claude API response: {response}")

                    answer = ""
                    for text_block in response.content:
                        self.logger.debug(f"TextBlock: {text_block}")
                        answer += text_block.text

                    if not answer.strip():
                        self.logger.error("Received empty response from Claude API.")
                        raise ValueError("Received empty response from Claude API.")

                    n_input_tokens, n_output_tokens = self._count_tokens_from_messages([], answer, model=self.model)
                else:
                    if self.model in {"gpt-3.5-turbo-16k", "gpt-3.5-turbo", "gpt-4", "gpt-4-1106-preview", "gpt-4-vision-preview", "gpt-4-turbo-2024-04-09", "gpt-4o"}:
                        messages = self._generate_prompt_messages(message, dialog_messages, chat_mode)
                        #GPT HELP 2
                        validate_payload({
                            "model": self.model,
                            "messages": messages,
                            **OPENAI_COMPLETION_OPTIONS
                        })
                        #GPT HELP 2
                        r = await openai.ChatCompletion.acreate(
                            model=self.model,
                            messages=messages,
                            **OPENAI_COMPLETION_OPTIONS
                        )
                        answer = r.choices[0].message["content"]
                    elif self.model == "text-davinci-003":
                        prompt = self._generate_prompt(message, dialog_messages, chat_mode)

                        #GPT HELP 2
                        validate_payload({
                            "model": self.model,
                            "messages": messages,
                            **OPENAI_COMPLETION_OPTIONS
                        })
                        #GPT HELP 2

                        r = await openai.Completion.acreate(
                            engine=self.model,
                            prompt=prompt,
                            **OPENAI_COMPLETION_OPTIONS
                        )
                        answer = r.choices[0].text
                    else:
                        raise ValueError(f"Unknown model: {self.model}")

                answer = self._postprocess_answer(answer)
                n_input_tokens, n_output_tokens = r.usage.prompt_tokens, r.usage.completion_tokens
            except openai.error.InvalidRequestError as e:  # too many tokens
                if len(dialog_messages) == 0:
                    raise ValueError("Dialog messages is reduced to zero, but still has too many tokens to make completion") from e

                # forget first message in dialog_messages
                dialog_messages = dialog_messages[1:]

        n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)

        return answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed

    async def send_message_stream(self, message, dialog_messages=[], chat_mode="assistant"):
        if chat_mode not in config.chat_modes.keys():
            raise ValueError(f"Chat mode {chat_mode} is not supported")

        n_dialog_messages_before = len(dialog_messages)
        answer = None
        n_input_tokens, n_output_tokens, n_first_dialog_messages_removed = 0, 0, 0
        while answer is None:
            try:
                if self.is_claude_model:
                    prompt = self._generate_claude_prompt(message, dialog_messages, chat_mode)

                    if not prompt.strip():
                        raise ValueError("Generated prompt is empty")
                    
                    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

                    async with client.messages.stream(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=1000,
                        temperature=0.0#0.7
                    ) as stream:
                        async for event in stream.text_stream:
                            #self.logger.debug(f"Event: {event}")
                            if event:
                                if isinstance(event, str):
                                    if answer is None:
                                        answer = event
                                    else:
                                        answer += event
                                    n_input_tokens, n_output_tokens = self._count_tokens_from_messages([], answer, model=self.model)
                                    yield "not_finished", answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed
   
                    if not answer.strip():
                        raise ValueError("Received empty response from Claude API.")

                else:

                    if self.model in {"gpt-3.5-turbo-16k", "gpt-3.5-turbo", "gpt-4", "gpt-4-1106-preview", "gpt-4-turbo-2024-04-09", "gpt-4o"}:
                        messages = self._generate_prompt_messages(message, dialog_messages, chat_mode)
                        
                        r_gen = await openai.ChatCompletion.acreate(
                            model=self.model,
                            messages=messages,
                            stream=True,
                            **OPENAI_COMPLETION_OPTIONS
                        )

                        answer = ""
                        async for r_item in r_gen:
                            delta = r_item.choices[0].delta

                            if "content" in delta:
                                answer += delta.content
                                n_input_tokens, n_output_tokens = self._count_tokens_from_messages(messages, answer, model=self.model)
                                n_first_dialog_messages_removed = 0  #n_dialog_messages_before - len(dialog_messages) #repo commit

                                yield "not_finished", answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed
                                
                    elif self.model == "text-davinci-003":
                        prompt = self._generate_prompt(message, dialog_messages, chat_mode)
                        r_gen = await openai.Completion.acreate(
                            engine=self.model,
                            prompt=prompt,
                            stream=True,
                            **OPENAI_COMPLETION_OPTIONS
                        )

                        answer = ""
                        async for r_item in r_gen:
                            answer += r_item.choices[0].text
                            n_input_tokens, n_output_tokens = self._count_tokens_from_prompt(prompt, answer, model=self.model)
                            n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)
                            yield "not_finished", answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed

                answer = self._postprocess_answer(answer)

            except openai.error.InvalidRequestError as e:  # too many tokens
                if len(dialog_messages) == 0:
                    raise e

                # forget first message in dialog_messages
                dialog_messages = dialog_messages[1:]
                n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)

        yield "finished", answer, (n_input_tokens, n_output_tokens), n_first_dialog_messages_removed  # sending final answer

    async def send_vision_message(
        self,
        message,
        dialog_messages=[],
        chat_mode="assistant",
        image_buffer: BytesIO = None,
    ):
        n_dialog_messages_before = len(dialog_messages)
        answer = None
        while answer is None:
            try:
                if self.model == "gpt-4-vision-preview":
                    messages = self._generate_prompt_messages(
                        message, dialog_messages, chat_mode, image_buffer
                    )
                    r = await openai.ChatCompletion.acreate(
                        model=self.model,
                        messages=messages,
                        **OPENAI_COMPLETION_OPTIONS
                    )
                    answer = r.choices[0].message.content
                else:
                    raise ValueError(f"Unsupported model: {self.model}")

                answer = self._postprocess_answer(answer)
                n_input_tokens, n_output_tokens = (
                    r.usage.prompt_tokens,
                    r.usage.completion_tokens,
                )
            except openai.error.InvalidRequestError as e:  # too many tokens
                if len(dialog_messages) == 0:
                    raise ValueError(
                        "Dialog messages is reduced to zero, but still has too many tokens to make completion"
                    ) from e

                # forget first message in dialog_messages
                dialog_messages = dialog_messages[1:]

        n_first_dialog_messages_removed = n_dialog_messages_before - len(
            dialog_messages
        )

        return (
            answer,
            (n_input_tokens, n_output_tokens),
            n_first_dialog_messages_removed,
        )

    async def send_vision_message_stream(
        self,
        message,
        dialog_messages=[],
        chat_mode="assistant",
        image_buffer: BytesIO = None,
    ):
        n_dialog_messages_before = len(dialog_messages)
        answer = None
        while answer is None:
            try:
                if self.model == "gpt-4-vision-preview":
                    messages = self._generate_prompt_messages(
                        message, dialog_messages, chat_mode, image_buffer
                    )
                    
                    r_gen = await openai.ChatCompletion.acreate(
                        model=self.model,
                        messages=messages,
                        stream=True,
                        **OPENAI_COMPLETION_OPTIONS,
                    )

                    answer = ""
                    async for r_item in r_gen:
                        delta = r_item.choices[0].delta
                        if "content" in delta:
                            answer += delta.content
                            (
                                n_input_tokens,
                                n_output_tokens,
                            ) = self._count_tokens_from_messages(
                                messages, answer, model=self.model
                            )
                            n_first_dialog_messages_removed = (
                                n_dialog_messages_before - len(dialog_messages)
                            )
                            yield "not_finished", answer, (
                                n_input_tokens,
                                n_output_tokens,
                            ), n_first_dialog_messages_removed

                answer = self._postprocess_answer(answer)

            except openai.error.InvalidRequestError as e:  # too many tokens
                if len(dialog_messages) == 0:
                    raise e
                # forget first message in dialog_messages
                dialog_messages = dialog_messages[1:]

        yield "finished", answer, (
            n_input_tokens,
            n_output_tokens,
        ), n_first_dialog_messages_removed
    


    def _generate_prompt(self, message, dialog_messages, chat_mode):
        prompt = config.chat_modes[chat_mode]["prompt_start"]
        prompt += "\n\n"

        # add chat context
        if len(dialog_messages) > 0:
            prompt += "Chat:\n"
            for dialog_message in dialog_messages:
                prompt += f"User: {dialog_message['user']}\n"
                prompt += f"Assistant: {dialog_message['bot']}\n"

        # current message
        prompt += f"User: {message}\n"
        prompt += "Assistant: "

        return prompt

    def _encode_image(self, image_buffer: BytesIO) -> bytes:
        return base64.b64encode(image_buffer.read()).decode("utf-8")

    def _generate_prompt_messages(self, message, dialog_messages, chat_mode, image_buffer: BytesIO = None):
        prompt = config.chat_modes[chat_mode]["prompt_start"]

        #messages = [{"role": "system", "content": config.chat_modes[chat_mode]["prompt_start"]}]
        messages = [{"role": "system", "content": prompt}] #repo commit

        for dialog_message in dialog_messages:
            messages.append({"role": "user", "content": dialog_message["user"]})
            messages.append({"role": "assistant", "content": dialog_message["bot"]})

        if image_buffer is not None:
            messages.append(
                {
                    "role": "user", 
                    "content": [
                        {
                            "type": "text",
                            "text": message,
                        },
                        {
                            "type": "image",
                            "image": self._encode_image(image_buffer),
                        }
                    ]
                }
                
            )
        else:
            messages.append({"role": "user", "content": message})

        return messages

    def _generate_claude_prompt(self, message, dialog_messages, chat_mode, image_buffer: BytesIO = None):
        prompt = config.chat_modes[chat_mode]["prompt_start"]
        combined_prompt = prompt

        for dialog_message in dialog_messages:
            combined_prompt += f"\n\nHuman: {dialog_message['user']}\n\nAssistant: {dialog_message['bot']}"

        if image_buffer is not None:
            encoded_image = self._encode_image(image_buffer)
            combined_prompt += f"\n\nHuman: {message}\n\nAssistant: [IMAGE: {encoded_image}]"
        else:
            combined_prompt += f"\n\nHuman: {message}"

        combined_prompt += "\n\nAssistant:"
        return combined_prompt

    def _postprocess_answer(self, answer):
        self.logger.debug(f"Pre-processed answer: {answer}")
        answer = answer.strip()
        self.logger.debug(f"Post-processed answer: {answer}")
        return answer

    def _count_tokens_from_messages(self, messages, answer, model="gpt-4-1106-preview"):

        if model.startswith("claude"):
            encoding = tiktoken.encoding_for_model("gpt-4-turbo-2024-04-09")
        else:
            encoding = tiktoken.encoding_for_model(model)

        tokens_per_message = 3
        tokens_per_name = 1

        if model.startswith("gpt-3"):
            tokens_per_message = 4 # every message follows <im_start>{role/name}\n{content}<im_end>\n
            tokens_per_name = -1 # if there's a name, the role is omitted
        elif model.startswith("gpt-4"):
            tokens_per_message = 3
            tokens_per_name = 1 
        elif model.startswith("claude"):
            tokens_per_message = 3
            tokens_per_name = 1 
        else:
            raise ValueError(f"Unknown model: {model}")

        # input
        n_input_tokens = 0
        for message in messages:
            n_input_tokens += tokens_per_message
            if isinstance(message["content"], list):
                for sub_message in message["content"]:
                    if "type" in sub_message:
                        if sub_message["type"] == "text":
                            n_input_tokens += len(encoding.encode(sub_message["text"]))
                        elif sub_message["type"] == "image_url":
                            pass
            else:
                if "type" in message:
                    if message["type"] == "text":
                        n_input_tokens += len(encoding.encode(message["text"]))
                    elif message["type"] == "image_url":
                        pass

        n_input_tokens += 2

        # output
        n_output_tokens = 1 + len(encoding.encode(answer))

        return n_input_tokens, n_output_tokens

    def _count_tokens_from_prompt(self, prompt, answer, model="text-davinci-003"):
        if model.startswith("claude"):
            encoding = tiktoken.encoding_for_model("gpt-4-turbo-2024-04-09")
        else:
            encoding = tiktoken.encoding_for_model(model)

        n_input_tokens = len(encoding.encode(prompt)) + 1
        n_output_tokens = len(encoding.encode(answer))

        return n_input_tokens, n_output_tokens
    
async def transcribe_audio(audio_file) -> str:
    r = await openai.Audio.atranscribe("whisper-1", audio_file)
    return r["text"] or ""


async def generate_images(prompt, model="dall-e-2", n_images=4, size="1024x1024", quality="standard"):
    """Generate images using OpenAI's specified model, including DALL-E 3."""
    #redundancy to make sure the api call isnt made wrong
    if model=="dalle-2":
        model="dall-e-2"
        quality="standard"

    if model=="dalle-3":
        model="dall-e-3"
        n_images=1
    # Make the API call to generate images using the specified model
    response = await openai.Image.acreate(
        model=model,
        prompt=prompt,
        n=n_images,
        size=size,
        quality=quality
    )

    # Extract image URLs from the response
    image_urls = [item.url for item in response.data]
    return image_urls


async def is_content_acceptable(prompt):
    r = await openai.Moderation.acreate(input=prompt)
    return not all(r.results[0].categories.values())
