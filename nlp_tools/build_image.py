from omegaconf import DictConfig
import docker
from pathlib import Path
from conf import cfg
import os
import hashlib
from workflows.utils import logx as Logx
import shutil


os.environ['DOCKER_CONTENT_TRUST'] = '0'
def calculate_md5(file_path):
    with open(file_path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8192)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8192)
    return file_hash.hexdigest()

def should_rebuild(dockerfile_path):
    md5_file = dockerfile_path.parent / "version.md5"
    current_md5 = calculate_md5(dockerfile_path)
    
    if not md5_file.exists():
        return True
    
    with open(md5_file, "r") as f:
        stored_md5 = f.read().strip()
    
    return current_md5 != stored_md5

def update_md5(dockerfile_path):
    md5_file = dockerfile_path.parent / "version.md5"
    current_md5 = calculate_md5(dockerfile_path)
    
    with open(md5_file, "w") as f:
        f.write(current_md5)
def build_docker_images():
    client = docker.from_env()
    logx = Logx()

    if not hasattr(cfg, 'container') or not cfg.container:
        logx.info("No function to containerize was found in the configuration.")
        return
    else : 
        logx.info(f"Building images for the following functions: {cfg.container}")
    to_rebuild = []
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    #docker_context = project_root / 'containerised_steps' / function_name
    for function_name in cfg.container:
        dockerfile_path = Path(f"containerised_steps/{function_name}/Dockerfile")
        docker_context = dockerfile_path.parent
        if should_rebuild(dockerfile_path):
            logx.info(f"Dockerfile {function_name} : rebuild")
            to_rebuild.append((function_name, dockerfile_path))
            shutil.copy2(project_root / 'pyproject.toml', docker_context)
            if (project_root / 'poetry.lock').exists():
                shutil.copy2(project_root / 'poetry.lock', docker_context)
            if (project_root / 'poetry.toml').exists():
                shutil.copy2(project_root / 'poetry.toml', docker_context)

        else:
            logx.info(f"Dockerfile {function_name} : up to date")




    for function_name, dockerfile_path in to_rebuild:
        logx.info(f"Building Docker image for {function_name}...")
        logx.info(dockerfile_path)
        if not dockerfile_path.exists():
            logx.error(f"Warning: Dockerfile for {function_name} does not exist at {dockerfile_path}")
            continue
        
        try:
            logx.info(f"Building Docker image for {function_name}...")
            

            build_generator = client.api.build(
                path=str(dockerfile_path.parent),
                tag=f"{function_name.lower()}",
                rm=True,
                decode=True,
                nocache=True
            )

            error_encountered = False
            for chunk in build_generator:
                if 'stream' in chunk:
                    logx.info(chunk['stream'].strip())
                elif 'error' in chunk:
                    logx.error(f"Error: {chunk['error'].strip()}")
                    error_encountered = True

            if not error_encountered:
                update_md5(dockerfile_path)
                continue

            logx.info(f"Docker image for {function_name} built successfully.")
            
        except docker.errors.BuildError as e:
            logx.error(f"Error while building image for {function_name}: {str(e)}")
        except Exception as e:
            logx.error(f"An unexpected error occurred while building image for {function_name}: {str(e)}")
        finally:
            for _, dockerfile_path in to_rebuild:
                docker_context = dockerfile_path.parent
                os.remove(os.path.join(docker_context, 'pyproject.toml'))
                if (project_root / 'poetry.lock').exists():
                    os.remove(os.path.join(docker_context, 'poetry.lock'))
                if (project_root / 'poetry.toml').exists():
                    os.remove(os.path.join(docker_context, 'poetry.toml'))

if __name__ == "__main__":
    build_docker_images()