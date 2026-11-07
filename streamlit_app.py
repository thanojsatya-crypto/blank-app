"""
Streamlit Community Cloud Entrypoint for Communication Base Station.
Runs the Communication Base Station application directly.
"""
import runpy
from pathlib import Path

APP_PATH = Path(__file__).resolve().parent / "communication_base_station.py"
runpy.run_path(str(APP_PATH), run_name="__main__")
