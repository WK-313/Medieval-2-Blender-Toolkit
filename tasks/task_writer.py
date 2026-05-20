import bpy
import subprocess
from glob import glob

#########################
######### Units #########
#########################

def unitTaskWriter():
    vanilla_path = bpy.context.scene.med2_toolkit_reader.directory_med2
    if bpy.context.scene.med2_toolkit_reader.mods_filtered != "custom":
        mod_path = bpy.context.scene.med2_toolkit_reader.mods_filtered[:-4]
    else:
        mod_path = bpy.context.scene.med2_toolkit_reader.directory_mod_data[:-5]
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    output_path = bpy.context.scene.med2_toolkit_reader.directory_models
    primary_secondary = bpy.context.scene.med2_toolkit_units.primary_secondary
    with open((iwte_path+'iwte_tasks/toolkit_bmdb_task.txt'), 'w') as task_file:
        task_file.writelines([
            '<task_id>                                  modeldb_mesh_to_extract''\n'
            '<mod_directory_in>                         "'+mod_path+'"\n'
            '<m2_directory_in>                          "'+vanilla_path+'"\n'
            '<directory_out>                            "'+output_path+'"\n'
            '<primary_or_secondary>                     '+primary_secondary+'\n'
            '<create_text_file>                         no\n'
            '\n'           
            '<modeldb_type_name_list>'
            ])

def unitTaskAppend(unit):
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    with open((iwte_path+'iwte_tasks/toolkit_bmdb_task.txt'), 'r') as task_file:
        lines = task_file.readlines()
    with open((iwte_path+'iwte_tasks/toolkit_bmdb_task.txt'), 'a') as task_file:
        if not unit in lines:
            task_file.write('\n'+unit)

def unitTaskRun():
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    task_file = iwte_path+"iwte_tasks/toolkit_bmdb_task.txt"
    iwte_exe = glob(iwte_path+"iwte*.exe")[0]
    subprocess.run([iwte_exe, "--uh", "--st", task_file], cwd = iwte_path)

#########################
######## Engines ########
#########################

def engineTaskWriter():
    vanilla_path = bpy.context.scene.med2_toolkit_reader.directory_med2
    if bpy.context.scene.med2_toolkit_reader.mods_filtered != "custom":
        mod_path = bpy.context.scene.med2_toolkit_reader.mods_filtered[:-4]
    else:
        mod_path = bpy.context.scene.med2_toolkit_reader.directory_mod_data[:-5]
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    output_path = bpy.context.scene.med2_toolkit_reader.directory_models
    with open((iwte_path+'iwte_tasks/toolkit_engine_task.txt'), 'w') as task_file:
        task_file.writelines([
            '<task_id>                                  m2_engines_to_extract''\n'
            '<mod_directory_in>                         "'+mod_path+'"\n'
            '<m2_directory_in>                          "'+vanilla_path+'"\n'
            '<directory_out>                            "'+output_path+'"\n'
            '<extract_file_type>                        '+'glb'+'\n'
            '\n'           
            '<engine_name_list>'
            ])

def engineTaskAppend(engine):
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    with open((iwte_path+'iwte_tasks/toolkit_engine_task.txt'), 'r') as task_file:
        lines = task_file.readlines()
    with open((iwte_path+'iwte_tasks/toolkit_engine_task.txt'), 'a') as task_file:
        if not engine in lines:
            task_file.write('\n'+engine)

def engineTaskRun():
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    task_file = iwte_path+"iwte_tasks/toolkit_engine_task.txt"
    iwte_exe = glob(iwte_path+"iwte*.exe")[0]
    subprocess.run([iwte_exe, "--uh", "--st", task_file], cwd = iwte_path)

#########################
###### Settlements ######
#########################

def settlementTaskWriter():
    vanilla_path = bpy.context.scene.med2_toolkit_reader.directory_med2
    if bpy.context.scene.med2_toolkit_reader.mods_filtered != "custom":
        mod_path = bpy.context.scene.med2_toolkit_reader.mods_filtered[:-4]
    else:
        mod_path = bpy.context.scene.med2_toolkit_reader.directory_mod_data[:-4]
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    output_path = bpy.context.scene.med2_toolkit_reader.directory_settlements
    with open((iwte_path+'iwte_tasks/toolkit_settlement_task.txt'), 'w') as task_file:
        task_file.writelines([
            '<task_id>                                  world_list_to_extract''\n'
            '<mod_directory_in>                         "'+mod_path+'"\n'
            '<m2_directory_in>                          "'+vanilla_path+'"\n'
            '<directory_out>                            "'+output_path+'"\n'
            '<extract_file_type>                        '+'glb'+'\n'
            '\n'           
            '<world_name_list>'
            ])

def settlementTaskAppend(settlement):
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    with open((iwte_path+'iwte_tasks/toolkit_settlement_task.txt'), 'r') as task_file:
        lines = task_file.readlines()
    with open((iwte_path+'iwte_tasks/toolkit_settlement_task.txt'), 'a') as task_file:
        if not settlement in lines:
            task_file.write('\n'+settlement)

def settlementTaskRun():
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    task_file = iwte_path+"iwte_tasks/toolkit_settlement_task.txt"
    iwte_exe = glob(iwte_path+"iwte*.exe")[0]
    subprocess.run([iwte_exe, "--uh", "--st", task_file], cwd = iwte_path)