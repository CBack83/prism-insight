"""
PRISM-INSIGHT 커스텀 예외 클래스
데이터 신뢰성 및 분석 안정성을 위한 예외 정의
"""


class DataSourceError(Exception):
    """필수 데이터 소스 연결 실패"""
    pass


class DataValidationError(Exception):
    """데이터 검증 실패"""
    pass


class CriticalDataSourceError(Exception):
    """치명적 데이터 소스 에러 - 즉시 중단 필요"""
    pass


class PriceDataMismatchError(Exception):
    """가격 데이터 불일치 에러"""
    pass


class ReportGenerationError(Exception):
    """보고서 생성 에러"""
    pass
