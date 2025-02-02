import asyncio
import httpx
import random
import time
import aiofiles
from tqdm.asyncio import tqdm_asyncio
from transformers import LlamaTokenizerFast
from langchain.prompts import PromptTemplate
from openai import AsyncOpenAI
from opentelemetry import trace
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
class AsyncResultDict(dict):
    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(value, asyncio.Task):
            if value.done():
                return value.result()
            else:
                return value
        return value

    def __str__(self):
        return self._format_dict()

    def __repr__(self):
        return self._format_dict()

    def _format_dict(self):
        formatted = {}
        for key, value in self.items():
            if isinstance(value, asyncio.Task):
                if value.done():
                    formatted[key] = value.result()
                else:
                    formatted[key] = f"<Task pending>"
            else:
                formatted[key] = value
        return repr(formatted)

class ParallelLLMInference:
    def __init__(self, 
                 base_url,exaion_model_name, 
                 exaion_api_key, 
                 hf_model_name,  
                 max_tokens, 
                 max_concurrent_requests, 
                 system_prompt_path, 
                 system_placeholder, 
                 user_prompt_path):
        span = trace.get_current_span()
        span.add_event("Initializing ParallelLLMInference")
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=exaion_api_key,
            timeout=60
        )
        self.tokenizer = LlamaTokenizerFast.from_pretrained(hf_model_name)
        self.max_tokens = max_tokens
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.exaion_model_name = exaion_model_name 
        self.system_prompt_path = system_prompt_path
        self.user_prompt_path = user_prompt_path
        self.system_placeholder = system_placeholder

    def chunk_speech(self,text):
        span = trace.get_current_span()
        span.add_event("Starting speech chunking")
        chunks = [[]] 
        prev = 0
        tokens = self.tokenizer.encode(text, add_special_tokens=False)
        if len(tokens) <= self.max_tokens * 0.9:
            span.add_event(f"Text fits in one chunk => direct return {len(tokens)} tokens")
            return [text]
        end_of_sentence_tokens = set([self.tokenizer.encode('test.', add_special_tokens=False)[-1],
                                     self.tokenizer.encode('test!', add_special_tokens=False)[-1],
                                     self.tokenizer.encode('test?', add_special_tokens=False)[-1]
                                     ])
        for i in range(len(tokens)):
            cur_sentence_len = i - prev + 1
            if tokens[i] in end_of_sentence_tokens or cur_sentence_len == self.max_tokens *0.9:
                if len(chunks[-1]) and len(chunks[-1]) + cur_sentence_len > self.max_tokens*0.9:
                    chunks.append([])
                chunks[-1].extend(tokens[prev:i+1])
                prev = i + 1

        if prev < len(tokens):
            if len(chunks[-1]) and len(chunks[-1]) + i - prev + 1 > self.max_tokens*0.9:
                chunks.append([])
            chunks[-1].extend(tokens[prev:i+1])

        span.add_event(f"Speech chunking completed. Number of chunks: {len(chunks)}")
        return [self.tokenizer.decode(chunk, add_special_tokens=False)for chunk in chunks]
    
    async def get_prompt_from_file(self, file_path):
        span = trace.get_current_span()
        span.add_event(f"Reading prompt from file: {file_path}")
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
            content = await file.read()
        span.add_event("Prompt file read successfully")
        return content

    async def infer_llm(self, text, system_prompt_path, system_placeholder, user_prompt_path):
        span = trace.get_current_span()
        span.add_event("Starting LLM inference")
        logger.info(f"Starting LLM inference")
        logger.info(f"Text: {text}")
        
        async with self.semaphore:
            system_prompt_template = await self.get_prompt_from_file(system_prompt_path)
            user_prompt = await self.get_prompt_from_file(user_prompt_path)

            system_prompt = PromptTemplate.from_template(system_prompt_template).format(system_value=system_placeholder)
            normalisation = PromptTemplate.from_template(user_prompt).format(text=text)

            retries = 5
            backoff_factor = 0.5
            
            logger.info(f"User prompt: {normalisation}")
            for attempt in range(retries):
                wait_time = backoff_factor * (2 ** attempt) + random.uniform(0, 1)
                try:
                    span.add_event(f"Attempt {attempt + 1} to call LLM API")
                    response = await self.client.chat.completions.create(
                        model=self.exaion_model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": normalisation}
                        ],
                        stream=False,
                        max_tokens=self.max_tokens
                    )

                    span.add_event("LLM API call successful")
                    result = response.choices[0].message.content.strip()
                    logger.info(f"Tour de parole traité Result: {result}")
                    return result
                except (httpx.HTTPStatusError, asyncio.TimeoutError, httpx.RemoteProtocolError) as e:
                    span.add_event(f"Error: {e}, retrying in {wait_time:.2f} seconds...")
                    logger.info(f"Error: {e}, retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    span.add_event(f"Unexpected error: {e}, retrying in {wait_time:.2f} seconds...")
                    logger.info(f"Unexpected error: {e}, retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
            span.add_event("Max retries exceeded for API call")
            logger.info(f"Max retries exceeded for API call")
            raise Exception("Max retries exceeded for API call")
    
    async def queue_api_calls(self, chunks, pbar=None):
        span = trace.get_current_span()
        span.add_event("Queueing API calls")
        logger.info(f"Queueing API calls")
        logger.info(f"Chunks: {chunks}")

        tasks = [
            self.infer_llm(chunk, self.system_prompt_path, self.system_placeholder, self.user_prompt_path)
            for chunk in chunks
        ]
        responses = await asyncio.gather(*tasks)
        if pbar:
            (pbar.update(1) for _ in range(len(responses)))
        span.add_event(f"API calls completed. Number of responses: {len(responses)}")
        logger.info(f"API calls completed. Number of responses: {responses}")
        result = " ".join(responses).strip()
        logger.info(f"Result: {result}")
        return result
    

    async def parallel_inference(self, segments):
        span = trace.get_current_span()
        span.add_event("Starting parallel inference")
        logger.info(f"Segments: Parallel Inf")
        tasks = []
        processed_segments = []
        #chunks_process = [(len(chunks := self.chunk_speech(segment["text"])), chunks,segment["speaker"]) for segment in segments]
        chunks_process = []
        speakers = []
        async with self.semaphore:
            for segment in segments:
                text = segment["text"]
                speaker = segment["speaker"]
                logger.info(f"Text: {text}")
                chunks = self.chunk_speech(text)
                logger.info(f"Chunks: {chunks}")
                #chunks_process.append((len(chunks), chunks, speaker))
                tasks.append(self.queue_api_calls(chunks))
                speakers.append(speaker)

        
                #total_chunks = sum(length for length, _, _ in chunks_process)

                # with tqdm_asyncio(total=total_chunks, desc="Processing") as pbar:
                #     for _ ,chunks,speaker in chunks_process:
                        
                #         future = asyncio.ensure_future(self.queue_api_calls(chunks, pbar))
                #         processed_segment = AsyncResultDict({
                #             "speaker": speaker,
                #             "text": future
                #         })
                #         processed_segments.append(processed_segment)
                #         tasks.append(future)

            results = await asyncio.gather(*tasks)
            processed_segments = [{"speaker": speaker, "text": result} for speaker, result in zip(speakers, results)]
            logger.info(f"Processed segments: {processed_segments}")
            with open("test_inf.json", "w") as f:
                json.dump(processed_segments, f, indent=4)
            span.add_event("Parallel inference completed")
            return processed_segments


    async def LLM_inference(self, segments):
        span = trace.get_current_span()
        span.add_event("Starting LLM inference")
        start = time.time()
        results = await self.parallel_inference(segments)
        end = time.time()
        processing_time = end - start
        span.add_event(f"Processing time: {processing_time} seconds")
        return results


