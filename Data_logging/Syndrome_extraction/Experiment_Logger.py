from datetime import datetime
from pathlib import Path
import json

class ExperimentLogger:
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_experiment(self, experiment_data: dict):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = self.log_dir / f"experiment_{timestamp}.json"
        with open(log_file, "w") as f:
            json.dump(experiment_data, f, indent=4)
        return log_file

    def get_log_dir(self):
        return self.log_dir

    def get_latest_log_file(self):
        log_files = list(self.log_dir.glob("experiment_*.json"))
        if not log_files:
            return None
        return max(log_files, key=lambda f: f.stat().st_mtime)

    def get_all_log_files(self):
        return list(self.log_dir.glob("experiment_*.json"))

    def get_log_file_by_timestamp(self, timestamp: str):
        log_file = self.log_dir / f"experiment_{timestamp}.json"
        if log_file.exists():
            return log_file
        return None

    def delete_log_file(self, log_file: Path):
        if log_file.exists():
            log_file.unlink()
            return True
        return False

    def delete_all_log_files(self):
        log_files = self.get_all_log_files()
        for log_file in log_files:
            log_file.unlink()
        return len(log_files)

    def clear_log_dir(self):
        return self.delete_all_log_files()

    def get_log_file_count(self):
        return len(self.get_all_log_files())

    def get_log_file_size(self, log_file: Path):
        if log_file.exists():
            return log_file.stat().st_size
        return None

    def get_total_log_file_size(self):
        log_files = self.get_all_log_files()
        total_size = 0
        for log_file in log_files:
            total_size += log_file.stat().st_size
        return total_size

    def get_log_file_modification_time(self, log_file: Path):
        if log_file.exists():
            return datetime.fromtimestamp(log_file.stat().st_mtime)
        return None

    def get_total_log_file_modification_time(self):
        log_files = self.get_all_log_files()
        total_modification_time = 0
        for log_file in log_files:
            total_modification_time += log_file.stat().st_mtime
        return total_modification_time


### Define the JSON structure for experiment data
experiment_data_template = {
    "timestamp": "",
    "steps": [],
    "qubits": [],
    "gates": [],
    "measurements": [],
    "errors": [],
    "shots": [],
    "metadata": {},
    "experiment_number": "",
    "parameters": {},
    "results": {}
}
