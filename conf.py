from hydra import  initialize, compose
import os

initialize(config_path="config", version_base="1.1")
cfg = compose(config_name="local")
api_key = cfg.llm_api.api_key
llm_model_name = cfg.llm_api.llm_model_name
base_url = cfg.llm_api.api_url
hf_model_name = cfg.llm_api.hf_model_name

device = cfg.architectures.device
batch_size = cfg.architectures.batch_size
compute_type = cfg.architectures.compute_type
model_name = cfg.architectures.model_name

senators_file_path = cfg.senators_file_path


max_tokens = cfg.max_tokens
max_concurrent_requests = cfg.max_concurrent_requests
language = cfg.language

os.environ["TOKENIZERS_PARALLELISM"] = cfg.architectures.tokenizer_parallelism