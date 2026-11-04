"""Electrical engineering enterprise domain. No legacy data import on startup."""
import os
for _key in ('LANGSMITH_TRACING','LANGCHAIN_TRACING_V2','HAYSTACK_TELEMETRY_ENABLED'):
    os.environ[_key]='false'
os.environ['OTEL_SDK_DISABLED']='true'
os.environ['DO_NOT_TRACK']='1'
