import logging
import contextvars
import uuid

trace_id_var = contextvars.ContextVar('trace_id', default='-')

class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = trace_id_var.get()
        return True

def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()
        
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [TraceID: %(trace_id)s] - %(message)s')
    handler.setFormatter(formatter)
    
    # Add filter to both the logger and handler for safety
    filter_instance = TraceIdFilter()
    handler.addFilter(filter_instance)
    logger.addFilter(filter_instance)
    
    logger.addHandler(handler)
    # Prevent log messages from being passed to the root logger's handlers
    logger.propagate = False 

    return logger

def set_trace_id(trace_id=None):
    if not trace_id:
        trace_id = str(uuid.uuid4())[:8]
    trace_id_var.set(trace_id)
    return trace_id
