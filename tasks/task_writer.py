import os
import bpy
import subprocess

from ..directories import modRoot, withTrailingSep
from .iwte_run import findIWTEExe

# Task files the toolkit writes for IWTE, all of them in IWTE's own iwte_tasks
# folder. Built with os.path.join rather than by adding strings: the Paths
# fields hold whatever the user typed, and a folder typed without its trailing
# separator used to give "...\IWTEiwte_tasks\toolkit_bmdb_task.txt" and a
# FileNotFoundError on every import.
TASK_FOLDER = 'iwte_tasks'


def taskPath(iwte_path, task_name):
    return os.path.join(bpy.path.abspath(iwte_path), TASK_FOLDER, task_name)


def modDirectory():
    """The mod folder for <mod_directory_in>, with its trailing separator.

    The Paths panel holds the mod's DATA folder either way round - the dropdown
    stores it without a trailing separator, the Manual Path field with one if it
    was browsed to and without one if it was typed - so the last component is
    dropped rather than a fixed number of characters cut off the end. The old
    code cut four or five depending on which field it read, which left the
    settlement task pointing at "...\\mymod\\d" whenever the path did end in a
    separator, and at the mod's data folder rather than the mod when it did not.
    """
    reader = bpy.context.scene.med2_toolkit_reader
    if reader.mods_filtered != "custom":
        return modRoot(reader.mods_filtered)
    return modRoot(reader.directory_mod_data)


def runTask(iwte_path, task_name):
    """Hand one task file to IWTE. The executable carries its version in its
    name, so it is matched by prefix rather than globbed onto the folder path."""
    iwte_dir = bpy.path.abspath(iwte_path)
    iwte_exe = findIWTEExe(iwte_dir)
    if not iwte_exe:
        raise FileNotFoundError('No IWTE executable found in %s' % iwte_dir)
    subprocess.run([iwte_exe, "--uh", "--st", taskPath(iwte_path, task_name)], cwd = iwte_dir)


def appendToTask(iwte_path, task_name, entry):
    task_file_path = taskPath(iwte_path, task_name)
    with open(task_file_path, 'r') as task_file:
        lines = task_file.readlines()
    with open(task_file_path, 'a') as task_file:
        if not entry in lines:
            task_file.write('\n'+entry)

#########################
######### Units #########
#########################

def unitTaskWriter():
    vanilla_path = withTrailingSep(bpy.context.scene.med2_toolkit_reader.directory_med2)
    mod_path = modDirectory()
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    output_path = withTrailingSep(bpy.context.scene.med2_toolkit_reader.directory_models)
    primary_secondary = bpy.context.scene.med2_toolkit_units.primary_secondary
    with open(taskPath(iwte_path, 'toolkit_bmdb_task.txt'), 'w') as task_file:
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
    appendToTask(bpy.context.scene.med2_toolkit_reader.directory_iwte, 'toolkit_bmdb_task.txt', unit)

def unitTaskRun():
    runTask(bpy.context.scene.med2_toolkit_reader.directory_iwte, 'toolkit_bmdb_task.txt')

#########################
######## Engines ########
#########################

def engineTaskWriter():
    vanilla_path = withTrailingSep(bpy.context.scene.med2_toolkit_reader.directory_med2)
    mod_path = modDirectory()
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    output_path = withTrailingSep(bpy.context.scene.med2_toolkit_reader.directory_models)
    with open(taskPath(iwte_path, 'toolkit_engine_task.txt'), 'w') as task_file:
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
    appendToTask(bpy.context.scene.med2_toolkit_reader.directory_iwte, 'toolkit_engine_task.txt', engine)

def engineTaskRun():
    runTask(bpy.context.scene.med2_toolkit_reader.directory_iwte, 'toolkit_engine_task.txt')

#########################
###### Settlements ######
#########################

def settlementTaskWriter():
    vanilla_path = withTrailingSep(bpy.context.scene.med2_toolkit_reader.directory_med2)
    mod_path = modDirectory()
    iwte_path = bpy.context.scene.med2_toolkit_reader.directory_iwte
    output_path = withTrailingSep(bpy.context.scene.med2_toolkit_reader.directory_settlements)
    with open(taskPath(iwte_path, 'toolkit_settlement_task.txt'), 'w') as task_file:
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
    appendToTask(bpy.context.scene.med2_toolkit_reader.directory_iwte, 'toolkit_settlement_task.txt', settlement)

def settlementTaskRun():
    runTask(bpy.context.scene.med2_toolkit_reader.directory_iwte, 'toolkit_settlement_task.txt')
