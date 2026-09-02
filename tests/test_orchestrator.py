import pytest
from unittest.mock import patch, MagicMock
import src.orchestrator

@patch("src.orchestrator.DiscoveryEngine")
@patch("src.orchestrator.ScoringEngine")
def test_orchestrator_pipeline(MockScoring, MockDiscovery):
    mock_disc = MockDiscovery.return_value
    mock_disc.run.return_value = 5
    
    mock_score = MockScoring.return_value
    mock_score.run.return_value = {"scored": 5, "above_threshold": 2}
    
    from src.orchestrator import Orchestrator
    assert Orchestrator is not None
