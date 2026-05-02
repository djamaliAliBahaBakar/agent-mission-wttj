from typing_extensions import TypedDict
from typing import Any, List
from typing import Optional
from typing import Literal



class Mission(TypedDict):
    name : str
    organization_name: str
    summary: str
    contract_type: str
    contract_duration_min: Optional[int]
    experience_level_minimum: Optional[float]
    remote: Optional[str]
    benefits : List[str]
    published_at: str
    slug: str
    url: str
    source: str

class MissionEvaluation(TypedDict):
    mission : Mission
    eligible: Optional[bool]
    justification : Optional[str]




class AgentMissionsState(TypedDict):
    #Les queries de recherche pour trouver les missions
    queries: Optional[List[str]]
    #Les missions à traiter
    missions_to_process: Optional[List[Mission]]
    # Slug des missions déjà traitées pour éviter les doublons
    process_slugs: Optional[set[str]]
    filtered_missions : Optional[List[MissionEvaluation]]

class ApiState(TypedDict):
    action: Optional[Literal["approve", "reject", "modify"]]
    updated_candidate: Optional[str]


class MissionState(TypedDict):
    mission: Mission
    candidate: Optional[str]
    updated_candidate: Optional[str]
    thread_id: Optional[str]
    decision: Optional[ApiState]
    email_sent: Optional[bool]
    counter: Optional[int]
    validate_status: Optional[Literal["ok","no_change","invalid"]]