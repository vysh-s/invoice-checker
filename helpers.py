"""
Invoice Checker - Helper Functions & Package Management
Centralized utilities for validation, and processing
Uses OpenAI API (GPT-3.5-turbo)
"""

import os
import json
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# PACKAGE IMPORTS
# ============================================================================

try:
    import streamlit as st
    from openai import OpenAI
    import pandas as pd
except ImportError as e:
    print(f"Missing package: {e}. Run: pip install -r requirements.txt")

# ============================================================================
# OPENAI CLIENT SETUP
# ============================================================================

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not found in .env file")

client = OpenAI(api_key=api_key)

# ============================================================================
# CONSTANTS
# ============================================================================

# Mock contractor database
CONTRACTOR_DATABASE = {
    "CONT_001": {
        "name": "Tech Solutions Inc",
        "agreed_rate": 150.0,
        "payment_terms": "Net 30",
        "tax_id": "12-3456789",
        "currency": "USD",
        "status": "active"
    },
    "CONT_002": {
        "name": "Design Studio Co",
        "agreed_rate": 120.0,
        "payment_terms": "Net 15",
        "tax_id": "98-7654321",
        "currency": "USD",
        "status": "active"
    },
    "CONT_003": {
        "name": "Marketing Pro Services",
        "agreed_rate": 100.0,
        "payment_terms": "Net 30",
        "tax_id": "55-5555555",
        "currency": "USD",
        "status": "active"
    },
}

# Invoice submission patterns (for anomaly detection)
INVOICE_HISTORY = {}

# ============================================================================
# VALIDATION RULES
# ============================================================================

def validate_invoice(extracted_data: Dict, contractor_id: str = None) -> Dict:
    """
    Runs compliance checks on extracted invoice data.
    
    Args:
        extracted_data: Extracted invoice fields
        contractor_id: Optional contractor ID for cross-reference
        
    Returns:
        Validation report with flags and severity
    """
    flags = []
    severity_level = "clean"
    
    # Check 1: Missing critical fields
    critical_fields = ["vendor_name", "invoice_number", "amount"]
    for field in critical_fields:
        if not extracted_data.get(field):
            flags.append({
                "type": "missing_field",
                "field": field,
                "severity": "high",
                "message": f"Missing required field: {field}"
            })
            severity_level = "high"
    
    # Check 2: Duplicate invoice detection
    invoice_key = f"{extracted_data.get('vendor_name')}_{extracted_data.get('invoice_number')}"
    if invoice_key in INVOICE_HISTORY:
        flags.append({
            "type": "duplicate_detected",
            "severity": "critical",
            "message": f"This invoice was already submitted on {INVOICE_HISTORY[invoice_key].get('submission_date', 'unknown').split('T')[0]}"
        })
        severity_level = "critical"
    
    # Check 3: Rate mismatch (if contractor_id provided)
    if contractor_id and contractor_id in CONTRACTOR_DATABASE:
        contractor = CONTRACTOR_DATABASE[contractor_id]
        agreed_rate = contractor["agreed_rate"]
        
        for line_item in extracted_data.get("line_items", []):
            if line_item.get("rate") and line_item.get("rate") != agreed_rate:
                flags.append({
                    "type": "rate_mismatch",
                    "severity": "medium",
                    "message": f"Invoice rate (${line_item.get('rate')}) doesn't match contractor agreement (${agreed_rate})",
                    "expected": agreed_rate,
                    "actual": line_item.get("rate")
                })
                severity_level = "medium" if severity_level != "high" else "high"
    
    # Check 4: Unusual amount (more than 2x average recent invoices)
    if invoice_key not in INVOICE_HISTORY:
        recent_amounts = [v.get("amount", 0) for v in list(INVOICE_HISTORY.values())[-5:]]
        current_amount = extracted_data.get("amount", 0)
        
        if recent_amounts and current_amount:
            avg_amount = sum(recent_amounts) / len(recent_amounts)
            if current_amount > avg_amount * 2:
                flags.append({
                    "type": "unusual_amount",
                    "severity": "medium",
                    "message": f"Amount (${current_amount}) is significantly higher than recent average (${avg_amount:.2f})",
                    "average": avg_amount,
                    "current": current_amount
                })
    
    # Check 5: Missing tax ID
    if not extracted_data.get("tax_id"):
        flags.append({
            "type": "missing_tax_id",
            "severity": "medium",
            "message": "Tax ID not found on invoice"
        })
    
    # Check 6: Payment terms mismatch
    if contractor_id and contractor_id in CONTRACTOR_DATABASE:
        expected_terms = CONTRACTOR_DATABASE[contractor_id]["payment_terms"]
        actual_terms = extracted_data.get("payment_terms")
        if actual_terms and actual_terms != expected_terms:
            flags.append({
                "type": "payment_terms_mismatch",
                "severity": "low",
                "message": f"Payment terms differ from agreement. Expected: {expected_terms}, Got: {actual_terms}",
                "expected": expected_terms,
                "actual": actual_terms
            })
    
    # Determine compliance score
    compliance_score = 100
    for flag in flags:
        if flag["severity"] == "critical":
            compliance_score -= 30
        elif flag["severity"] == "high":
            compliance_score -= 20
        elif flag["severity"] == "medium":
            compliance_score -= 10
        elif flag["severity"] == "low":
            compliance_score -= 5
    
    compliance_score = max(0, compliance_score)
    
    return {
        "flags": flags,
        "compliance_score": compliance_score,
        "severity_level": severity_level,
        "requires_manual_review": severity_level in ["critical", "high"],
        "processing_time_estimate": estimate_processing_time(compliance_score)
    }


# ============================================================================
# ANOMALY DETECTION
# ============================================================================

def detect_submission_patterns(contractor_id: str, extracted_data: Dict) -> Dict:
    """
    Analyzes submission patterns for a contractor to detect anomalies.
    """
    contractor_invoices = [
        v for k, v in INVOICE_HISTORY.items() 
        if v.get("contractor_id") == contractor_id
    ]
    
    anomalies = []
    
    if len(contractor_invoices) > 0:
        dates = [datetime.fromisoformat(v["submission_date"]) for v in contractor_invoices]
        if len(dates) > 1:
            dates.sort()
            intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
            avg_interval = sum(intervals) / len(intervals)
            
            last_submission = (datetime.now() - dates[-1]).days
            if last_submission < avg_interval * 0.5:
                anomalies.append({
                    "type": "unusual_frequency",
                    "message": f"Contractor submitting more frequently than usual (every {last_submission} days vs average {avg_interval:.0f})"
                })
    
    return {
        "anomalies": anomalies,
        "submission_history_count": len(contractor_invoices),
        "risk_level": "high" if len(anomalies) > 0 else "low"
    }


# ============================================================================
# PROCESSING TIME ESTIMATION
# ============================================================================

def estimate_processing_time(compliance_score: int) -> str:
    """
    Estimates processing time based on compliance score.
    """
    if compliance_score >= 90:
        return "~15 minutes (Auto-approval eligible)"
    elif compliance_score >= 70:
        return "~30-45 minutes (Quick review)"
    elif compliance_score >= 50:
        return "~1-2 hours (Standard review)"
    else:
        return "~2-4 hours (Detailed review required)"


# ============================================================================
# CONTRACTOR LOOKUP
# ============================================================================

def get_contractor_info(contractor_id: str) -> Optional[Dict]:
    """
    Retrieves contractor information from database.
    """
    return CONTRACTOR_DATABASE.get(contractor_id)


def list_all_contractors() -> List[Tuple[str, str]]:
    """
    Returns list of all contractors (ID, Name) for dropdown selection.
    """
    return [(cid, data["name"]) for cid, data in CONTRACTOR_DATABASE.items()]


# ============================================================================
# INVOICE LOGGING & TRACKING
# ============================================================================

def log_invoice_submission(contractor_id: str, extracted_data: Dict, validation_result: Dict):
    """
    Logs invoice submission for pattern analysis and tracking.
    """
    invoice_key = f"{extracted_data.get('vendor_name')}_{extracted_data.get('invoice_number')}"
    
    INVOICE_HISTORY[invoice_key] = {
        "contractor_id": contractor_id,
        "vendor_name": extracted_data.get("vendor_name"),
        "invoice_number": extracted_data.get("invoice_number"),
        "amount": extracted_data.get("amount"),
        "submission_date": datetime.now().isoformat(),
        "compliance_score": validation_result.get("compliance_score"),
        "severity": validation_result.get("severity_level")
    }


def get_invoice_history_summary() -> str:
    """
    Returns a summary of recent invoice submissions.
    """
    if not INVOICE_HISTORY:
        return "No invoices processed yet."
    
    total_invoices = len(INVOICE_HISTORY)
    total_amount = sum(v.get("amount") or 0 for v in INVOICE_HISTORY.values())
    avg_compliance = sum(v.get("compliance_score", 0) for v in INVOICE_HISTORY.values()) / total_invoices
    
    return f"Invoices processed: {total_invoices} | Total amount: ${total_amount:,.2f} | Avg compliance: {avg_compliance:.1f}%"


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def format_currency(amount: float, currency: str = "USD") -> str:
    """
    Formats amount as currency string.
    """
    if currency == "USD":
        return f"${amount:,.2f}"
    else:
        return f"{currency} {amount:,.2f}"


def validate_email(email: str) -> bool:
    """
    Simple email validation.
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes filename for safe file operations.
    """
    return re.sub(r'[<>:"/\\|?*]', '', filename)