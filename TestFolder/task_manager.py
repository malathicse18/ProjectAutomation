import os
import sys
import shutil
import time
import logging
import json
import argparse
import requests
import smtplib
import zipfile
import tarfile
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pymongo import MongoClient
from docx import Document
import pandas as pd
from fpdf import FPDF
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class TaskManager:
    def __init__(self):
        """Initialize TaskManager with logging, MongoDB, and scheduler."""
        # Logging Configuration
        logging.basicConfig(
            filename="task_manager.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(__name__)

        # MongoDB Configuration
        self.mongo_uri = "mongodb://localhost:27017/"
        self.client = MongoClient(self.mongo_uri)
        self.db = self.client["task_manager_db"]
        self.logs_collection = self.db["logs"]

        # Scheduler Configuration
        self.scheduler = BackgroundScheduler()

        # Task Storage File
        self.tasks_file = "scheduled_tasks.json"

        # File Types for Organization
        self.file_types = {
            "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".svg"],
            "Videos": [".mp4", ".mkv", ".flv", ".mov", ".avi", ".wmv"],
            "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"],
            "Audio": [".mp3", ".wav", ".aac", ".flac", ".ogg"],
            "Archives": [".zip", ".rar", ".tar", ".gz", ".7z"],
            "Executables": [".exe", ".msi", ".bat", ".sh"],
            "Code": [".py", ".js", ".html", ".css", ".java", ".cpp", ".c", ".php"],
            "Data": [".csv", ".json", ".xml", ".sql", ".db"],
        }

        # Load and schedule existing tasks
        self.load_and_schedule_tasks()

    def log_to_mongodb(self, task_name, details, status, level="INFO"):
        """Log actions to MongoDB."""
        log_entry = {
            "task_name": task_name,
            "details": details,
            "status": status,
            "level": level,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.logs_collection.insert_one(log_entry)

    def load_tasks(self):
        """Load tasks from the JSON file."""
        try:
            with open(self.tasks_file, "r") as f:
                tasks = json.load(f)
                return tasks if isinstance(tasks, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_tasks(self, tasks):
        """Save tasks to the JSON file."""
        with open(self.tasks_file, "w") as f:
            json.dump(tasks, f, indent=4)

    def organize_files(self, directory):
        """Organize files in the given directory based on their extensions."""
        try:
            files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
            for file in files:
                file_extension = os.path.splitext(file)[1].lower()
                category = "Others"
                for folder_name, extensions in self.file_types.items():
                    if file_extension in extensions:
                        category = folder_name
                        break
                category_folder = os.path.join(directory, category)
                if not os.path.exists(category_folder):
                    os.makedirs(category_folder)
                shutil.move(os.path.join(directory, file), os.path.join(category_folder, file))
                self.logger.info(f"Moved '{file}' to '{category}' folder.")
                self.log_to_mongodb("organize_files", {"file": file, "category": category}, "File moved")
            self.logger.info(f"File organization in '{directory}' completed successfully.")
            self.log_to_mongodb("organize_files", {"directory": directory}, "Organization completed")
        except Exception as e:
            self.logger.error(f"Error organizing files in '{directory}': {e}")
            self.log_to_mongodb("organize_files", {"directory": directory, "error": str(e)}, "Error", level="ERROR")

    def add_task(self, interval, unit, task_type, **kwargs):
        """Add a new task to the scheduler."""
        tasks = self.load_tasks()
        task_name = f"{task_type}_task_{len(tasks) + 1}"
        trigger = IntervalTrigger(**{unit: interval})

        if task_type == "organize_files":
            self.scheduler.add_job(self.organize_files, trigger, args=[kwargs["directory"]], id=task_name)
        elif task_type == "delete_files":
            self.scheduler.add_job(self.delete_files, trigger, args=[kwargs["directory"], kwargs["age_days"], kwargs["formats"]], id=task_name)
        elif task_type == "send_email":
            self.scheduler.add_job(self.send_email, trigger, args=[kwargs["recipient_email"], kwargs["subject"], kwargs["message"], kwargs["attachments"]], id=task_name)
        elif task_type == "get_gold_rate":
            self.scheduler.add_job(self.get_gold_rate, trigger, id=task_name)
        elif task_type == "convert_file":
            self.scheduler.add_job(self.convert_file, trigger, args=[kwargs["input_path"], kwargs["output_path"], kwargs["input_format"], kwargs["output_format"]], id=task_name)
        elif task_type == "compress_files":
            self.scheduler.add_job(self.compress_files, trigger, args=[kwargs["directory"], kwargs["output_path"], kwargs["compression_format"]], id=task_name)
        else:
            raise ValueError("Unsupported task type")

        tasks[task_name] = {"interval": interval, "unit": unit, "task_type": task_type, **kwargs}
        self.save_tasks(tasks)
        self.logger.info(f"Added task '{task_name}'")
        self.log_to_mongodb("add_task", {"task_name": task_name, "details": tasks[task_name]}, "Task added")

    def start_scheduler(self):
        """Start the scheduler."""
        self.scheduler.start()
        print("Scheduler started. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Scheduler stopped.")
            self.scheduler.shutdown()

    def load_and_schedule_tasks(self):
        """Load and schedule tasks from the JSON file."""
        tasks = self.load_tasks()
        for task_name, details in tasks.items():
            trigger = IntervalTrigger(**{details["unit"]: details["interval"]})
            if details["task_type"] == "organize_files":
                self.scheduler.add_job(self.organize_files, trigger, args=[details["directory"]], id=task_name)
            elif details["task_type"] == "delete_files":
                self.scheduler.add_job(self.delete_files, trigger, args=[details["directory"], details["age_days"], details["formats"]], id=task_name)
            elif details["task_type"] == "send_email":
                self.scheduler.add_job(self.send_email, trigger, args=[details["recipient_email"], details["subject"], details["message"], details["attachments"]], id=task_name)
            elif details["task_type"] == "get_gold_rate":
                self.scheduler.add_job(self.get_gold_rate, trigger, id=task_name)
            elif details["task_type"] == "convert_file":
                self.scheduler.add_job(self.convert_file, trigger, args=[details["input_path"], details["output_path"], details["input_format"], details["output_format"]], id=task_name)
            elif details["task_type"] == "compress_files":
                self.scheduler.add_job(self.compress_files, trigger, args=[details["directory"], details["output_path"], details["compression_format"]], id=task_name)

# CLI Interface
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Task Manager CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Add Task Parser
    add_parser = subparsers.add_parser("add", help="Add a new task")
    add_parser.add_argument("--interval", type=int, required=True, help="Interval for the task")
    add_parser.add_argument("--unit", type=str, required=True, choices=["seconds", "minutes", "hours", "days"], help="Time unit for the interval")
    add_parser.add_argument("--task-type", type=str, required=True, choices=["organize_files", "delete_files", "send_email", "get_gold_rate", "convert_file", "compress_files"], help="Type of task")
    add_parser.add_argument("--directory", type=str, help="Directory for file tasks")
    add_parser.add_argument("--age-days", type=int, help="Age in days for file deletion")
    add_parser.add_argument("--formats", nargs="*", help="File formats for deletion or conversion")
    add_parser.add_argument("--recipient-email", type=str, help="Recipient email address")
    add_parser.add_argument("--subject", type=str, help="Email subject")
    add_parser.add_argument("--message", type=str, help="Email message")
    add_parser.add_argument("--attachments", nargs="*", help="Email attachments")
    add_parser.add_argument("--input-path", type=str, help="Input file path for conversion")
    add_parser.add_argument("--output-path", type=str, help="Output file path for conversion or compression")
    add_parser.add_argument("--input-format", type=str, help="Input file format for conversion")
    add_parser.add_argument("--output-format", type=str, help="Output file format for conversion")

    # Parse arguments
    args = parser.parse_args()

    # Initialize TaskManager
    task_manager = TaskManager()

    # Handle "add" command
    if args.command == "add":
        task_manager.add_task(
            interval=args.interval,
            unit=args.unit,
            task_type=args.task_type,
            directory=args.directory,
            age_days=args.age_days,
            formats=args.formats,
            recipient_email=args.recipient_email,
            subject=args.subject,
            message=args.message,
            attachments=args.attachments,
            input_path=args.input_path,
            output_path=args.output_path,
            input_format=args.input_format,
            output_format=args.output_format
        )
        print(f"Task added: {args.task_type}")

    # Start the scheduler
    task_manager.start_scheduler()
