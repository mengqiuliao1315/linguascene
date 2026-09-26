from pydantic import BaseModel, ConfigDict


class PetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    species: str
    name: str = ""
    mood: str
    # 见面前的心情；前端先播它，再切到 mood，形成「难过 -> 开心」的过渡
    previous_mood: str | None = None
    days_away: int = 0
    login_streak: int = 0
    best_login_streak: int = 0
    study_streak: int = 0
    last_login_date: str | None = None


class UpdatePetRequest(BaseModel):
    species: str | None = None
    name: str | None = None
