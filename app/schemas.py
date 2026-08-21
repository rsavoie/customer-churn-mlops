from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CustomerFeatures(BaseModel):
    customerID: Optional[str] = Field(default=None)
    gender: str
    SeniorCitizen: int
    Partner: str
    Dependents: str
    tenure: int
    PhoneService: str
    MultipleLines: str
    InternetService: str
    OnlineSecurity: str
    OnlineBackup: str
    DeviceProtection: str
    TechSupport: str
    StreamingTV: str
    StreamingMovies: str
    Contract: str
    PaperlessBilling: str
    PaymentMethod: str
    MonthlyCharges: float
    TotalCharges: Optional[float] = None


class BatchScoreRequest(BaseModel):
    customers: list[CustomerFeatures]


class PredictionResponse(BaseModel):
    customer_id: Optional[str]
    churn_probability: float
    churn_prediction: bool
    priority_score: float
    decision: str
    backend: str
    model_version: str


class BatchScoreResponse(BaseModel):
    count: int
    predictions: list[PredictionResponse]
