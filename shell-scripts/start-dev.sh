#!/usr/bin/env bash
# Start the development server for the FastAPI application
uvicorn main:app --reload --host 0.0.0.0 --port 8000