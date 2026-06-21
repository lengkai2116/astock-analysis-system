from typing import Dict, List, Optional
from datetime import date
from app.models.strategy import (
    StrategyOutput, StrategySignal, StrategyTemplateV2
)
from app import db

class StrategyOutputService:
    @staticmethod
    def create_strategy_output(
        ts_code: str,
        strategy_name: str,
        signal: str,
        signal_date: date,
        confidence: Optional[float] = None,
        entry_zone: Optional[List[float]] = None,
        risk_line: Optional[float] = None,
        target_zone: Optional[List[float]] = None,
        position_suggestion: Optional[str] = None,
        holding_period: Optional[str] = None,
        evidence: Optional[List[str]] = None,
        risk_notes: Optional[List[str]] = None,
        status_recognition: Optional[Dict] = None
    ) -> StrategyOutput:
        output = StrategyOutput(
            ts_code=ts_code,
            strategy_name=strategy_name,
            signal=StrategySignal(signal),
            signal_date=signal_date,
            confidence=confidence,
            position_suggestion=position_suggestion,
            holding_period=holding_period,
            evidence=evidence or [],
            risk_notes=risk_notes or []
        )

        if entry_zone and len(entry_zone) >= 2:
            output.entry_zone_low = entry_zone[0]
            output.entry_zone_high = entry_zone[1]

        output.risk_line = risk_line

        if target_zone and len(target_zone) >= 2:
            output.target_zone_low = target_zone[0]
            output.target_zone_high = target_zone[1]

        if status_recognition:
            output.status_recognition = status_recognition

        db.session.add(output)
        db.session.commit()
        return output
    
    @staticmethod
    def get_strategy_outputs(
        ts_code: Optional[str] = None,
        strategy_name: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100
    ) -> List[StrategyOutput]:
        query = StrategyOutput.query
        
        if ts_code:
            query = query.filter_by(ts_code=ts_code)
        if strategy_name:
            query = query.filter_by(strategy_name=strategy_name)
        if start_date:
            query = query.filter(StrategyOutput.signal_date >= start_date)
        if end_date:
            query = query.filter(StrategyOutput.signal_date <= end_date)
        
        return query.order_by(StrategyOutput.signal_date.desc()).limit(limit).all()
    
    @staticmethod
    def get_latest_signal(ts_code: str) -> Optional[StrategyOutput]:
        return StrategyOutput.query.filter_by(ts_code=ts_code).order_by(
            StrategyOutput.signal_date.desc()
        ).first()
    
    @staticmethod
    def delete_strategy_output(output_id: int) -> bool:
        output = StrategyOutput.query.get(output_id)
        if output:
            db.session.delete(output)
            db.session.commit()
            return True
        return False
