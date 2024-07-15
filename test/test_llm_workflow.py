
import pathlib

import spacy
import epitran


from similarity.jarowinkler import JaroWinkler
from pydub import AudioSegment

import asyncio
from workflows.pipeline import Pipeline, Step,Parameters
from workflows.nlp_steps import (transcribe_empty, 
                       parse_whisperx_output, 
                       format_for_output, 
                       spell_correct, 
                       step_llm_inference)
from conf  import cfg , senators_file_path

               


jarowinkler = JaroWinkler()
epi = epitran.Epitran(cfg["epi"])
nlp = spacy.load(cfg["nlp"])


transcription = Step(transcribe_empty)
transcription.set_params(Parameters(args = [20]))
parse_transcription = Step(parse_whisperx_output)
formatted_verbatim = Step(format_for_output)
c_transcription_list = Step(spell_correct)
c_transcription_list.set_params(Parameters(args = [senators_file_path, epi, nlp, jarowinkler]
                                            ,kwargs={"verbose":True}))


c_verbatim_output = Step(step_llm_inference)
c_verbatim_output.set_params(Parameters(args = [
                                                cfg.placeholders.correction,             
                                                cfg.prompts.normalisation,
                                                cfg]))
parsed_cri = Step(step_llm_inference)
parsed_cri.set_params(Parameters(args = [
                                        cfg.placeholders.redaction,
                                        cfg.prompts.cri,
                                        cfg]))
parsed_cra = Step(step_llm_inference)
parsed_cra.set_params(Parameters(args = [
                                        cfg.placeholders.redaction,
                                        cfg.prompts.cra,
                                        cfg]))
parsed_cred = Step(step_llm_inference)
parsed_cred.set_params(Parameters(args = [
                                        cfg.placeholders.redaction,
                                        cfg.prompts.cred,
                                        cfg]))

llm_workflow= Pipeline()

async def main():
    data_dir = pathlib.Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    audio_file = "transcribe_encoded.json"
    audio_path = data_dir / audio_file


    if 'mp3' in audio_file:
        sound = AudioSegment.from_mp3("/Users/chrysostomebeltran/Downloads/exercise/data/DCR_POC_CRA_1.mp3")
        audio_path_wav = audio_path.with_suffix('.wav')
        sound.export(audio_path_wav, format="wav", parameters=["-ar", "16000", "-ac", "1", "-ab", "32k"])
        audio_path = audio_path_wav



    llm_workflow >> transcription >> parse_transcription >> formatted_verbatim >> c_transcription_list 
    llm_workflow | c_transcription_list >> c_verbatim_output + parsed_cri + parsed_cra + parsed_cred

    results = asyncio.create_task(llm_workflow.start(audio_path))
    results = await results
    print(results)


if __name__ == "__main__":

    asyncio.run(main())