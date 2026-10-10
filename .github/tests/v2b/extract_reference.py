"""Extract four real strat fixtures through IWTE; bounded test-owned processes.
Set MED2_IWTE_EXE and MED2_MOD_DATA to override local fixture paths.
"""
from pathlib import Path
import os, subprocess, tempfile, time, json
out=Path(tempfile.gettempdir())/'med2-v2b-iwte'
out.mkdir(exist_ok=True)
data=Path(os.environ.get('MED2_MOD_DATA',r'C:\Program Files (x86)\Steam\steamapps\common\Medieval II Total War\mods\Divide_and_Conquer_EUR\data'))
exe=Path(os.environ['MED2_IWTE_EXE'])
results=[]
for kind in ('assassin','diplomat','spy','general'):
    source=data/'models_strat'/('dunedain_'+kind+'.cas')
    output=out/(kind+'.glb')
    fields={'task_id':'cas_to_extract','cas_mesh_file_full_path_in':f'"{source.as_posix()}"','directory_out':f'"{out.as_posix()}/"','extract_file_name_out':f'"{kind}.glb"','cas_animation_file_format':'m2','extract_file_type':'glb','create_text_file':'no','create_task_file_from_input':'no'}
    task=out/(kind+'_task.txt')
    task.write_text('\n'.join(f'<{k}> {v}' for k,v in fields.items())+'\n')
    started=time.time()
    with (out/(kind+'-stdout.log')).open('w') as log:
        process=subprocess.Popen([str(exe),'--uh','--st',task.as_posix()],cwd=str(exe.parent),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            status=process.wait(timeout=100)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
            raise RuntimeError('IWTE timed out: '+kind)
    if not output.exists() or output.stat().st_mtime < started:
        raise RuntimeError('IWTE produced no fresh GLB: '+kind+' (exit '+str(status)+')')
    print('PASS IWTE reference',kind,output.stat().st_size,flush=True)
    results.append({'kind':kind,'path':str(output),'bytes':output.stat().st_size,'exit_code':status})
(Path(__file__).resolve().parent/'iwte-results.json').write_text(json.dumps(results,indent=2))
