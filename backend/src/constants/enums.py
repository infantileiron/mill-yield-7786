from enum import Enum
class Role(str,Enum):
    admin="admin"
    analyst="analyst"
    viewer="viewer"
class ReviewStatus(str,Enum):
    queued="queued"
    running="running"
    completed="completed"
    approved="approved"
    failed="failed"
class PackageStatus(str,Enum):
    pending="pending"
    accepted="accepted"
LINES=["一线","二线","三线"]
