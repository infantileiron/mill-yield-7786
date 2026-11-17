from pydantic import BaseModel,Field,field_validator
from typing import Literal
class Login(BaseModel):
    email:str
    password:str
class BatchInput(BaseModel):
    code:str=Field(min_length=3,max_length=50,pattern=r"^[A-Za-z0-9_-]+$")
    line:Literal["一线","二线","三线"]
    supplier:str=Field(min_length=1,max_length=80)
    tonnes:float=Field(gt=0,le=10000,allow_inf_nan=False)
    received_date:str
    @field_validator('received_date')
    @classmethod
    def valid_date(cls,v):
        from datetime import date
        date.fromisoformat(v)
        return v
class InspectionInput(BaseModel):
    sample_code:str=Field(min_length=3,max_length=70,pattern=r"^[A-Za-z0-9_-]+$")
    batch_id:int=Field(gt=0)
    flour_yield:float=Field(gt=0,le=100,allow_inf_nan=False)
    moisture:float=Field(ge=0,le=30,allow_inf_nan=False)
    inspector:str=Field(min_length=1,max_length=50)
class ReviewInput(BaseModel):
    title:str=Field(min_length=2,max_length=120)
    line:Literal["全部","一线","二线","三线"]="全部"
class ApprovalInput(BaseModel):
    note:str=Field(min_length=5,max_length=1500)
class OfflineBatch(BaseModel):
    code:str=Field(min_length=3,max_length=50,pattern=r"^[A-Za-z0-9_-]+$")
    line:Literal["一线","二线","三线"]
    supplier:str=Field(min_length=1,max_length=80)
    tonnes:float=Field(gt=0,le=10000,allow_inf_nan=False)
    received_date:str
    @field_validator('received_date')
    @classmethod
    def valid_date(cls,v):
        from datetime import date
        date.fromisoformat(v)
        return v
class OfflineInspection(BaseModel):
    sample_code:str=Field(min_length=3,max_length=70,pattern=r"^[A-Za-z0-9_-]+$")
    batch_code:str=Field(min_length=3,max_length=50,pattern=r"^[A-Za-z0-9_-]+$")
    flour_yield:float=Field(gt=0,le=100,allow_inf_nan=False)
    moisture:float=Field(ge=0,le=30,allow_inf_nan=False)
    inspector:str=Field(min_length=1,max_length=50)
class OfflinePackageInput(BaseModel):
    baseline:str=Field(min_length=1,max_length=80)
    site:str=Field(min_length=1,max_length=50)
    added_batches:list[OfflineBatch]=[]
    added_inspections:list[OfflineInspection]=[]
class Resolution(BaseModel):
    type:Literal["batch","inspection"]
    code:str=Field(min_length=1,max_length=70)
    action:Literal["use_online","rename"]
    new_code:str|None=Field(default=None,min_length=3,max_length=70,pattern=r"^[A-Za-z0-9_-]+$")
class ResolveInput(BaseModel):
    resolutions:list[Resolution]=[]
