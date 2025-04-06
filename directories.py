
from pathlib import Path
import pickle
script_folder = Path(__file__).parent
directories = {
    "directory_mod": "C:\\Program Files",
    "directory_units": "C:\\Program Files",
    "directory_output": "C:\\Program Files",
    "directory_strat": "C:\\Program Files",
    "directory_single_dae": "C:\\Program Files"
}
with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
    pickle.dump(directories, directories_output)