from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

Style = Literal['cinematic', 'natural', 'film']
Strategy = Literal['protect_highlights', 'lift_shadows', 'preserve_skin', 'soften_contrast', 'enhance_depth', 'restrain_color']

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class WhiteBalance(StrictModel):
    mode: Literal['preserve','as_shot','custom'] = 'preserve'
    temperature: int = Field(default=5500, ge=2000, le=50000)
    tint: float = Field(default=0, ge=-150, le=150)

class Vignette(StrictModel):
    amount: float = Field(default=0, ge=-100, le=100)
    style: Literal[1,2,3] = 1
    midpoint: float = Field(default=50, ge=0, le=100)
    roundness: float = Field(default=0, ge=-100, le=100)
    feather: float = Field(default=50, ge=0, le=100)
    highlights: float = Field(default=0, ge=0, le=100)

class Correction(StrictModel):
    exposure_ev: float = Field(default=0, ge=-1, le=1)
    highlights: float = Field(default=0, ge=-100, le=30)
    shadows: float = Field(default=0, ge=-40, le=60)
    whites: float = Field(default=0, ge=-60, le=40)
    white_balance: WhiteBalance = Field(default_factory=WhiteBalance)

class ColorTarget(StrictModel):
    color: Literal['Red','Orange','Yellow','Green','Aqua','Blue','Purple','Magenta']
    hue: float = Field(default=0, ge=-50, le=50)
    saturation: float = Field(default=0, ge=-60, le=60)
    luminance: float = Field(default=0, ge=-50, le=50)

class CurvePoint(StrictModel):
    x: int = Field(ge=0, le=255)
    y: int = Field(ge=0, le=255)

def validate_curve_points(points):
    if points[0].x != 0 or points[-1].x != 255 or any(b.x <= a.x or b.y < a.y for a,b in zip(points,points[1:])):
        raise ValueError('曲线必须覆盖 0–255，且横坐标严格递增、纵坐标不下降。')

def linear_curve():
    return [CurvePoint(x=0,y=0),CurvePoint(x=255,y=255)]

class Calibration(StrictModel):
    shadow_tint: float = Field(default=0, ge=-100, le=100)
    red_hue: float = Field(default=0, ge=-100, le=100)
    red_saturation: float = Field(default=0, ge=-100, le=100)
    green_hue: float = Field(default=0, ge=-100, le=100)
    green_saturation: float = Field(default=0, ge=-100, le=100)
    blue_hue: float = Field(default=0, ge=-100, le=100)
    blue_saturation: float = Field(default=0, ge=-100, le=100)

class ParametricCurve(StrictModel):
    highlights: float = Field(default=0, ge=-100, le=100)
    lights: float = Field(default=0, ge=-100, le=100)
    darks: float = Field(default=0, ge=-100, le=100)
    shadows: float = Field(default=0, ge=-100, le=100)
    shadow_split: int = Field(default=25, ge=10, le=70)
    midtone_split: int = Field(default=50, ge=20, le=80)
    highlight_split: int = Field(default=75, ge=30, le=90)

    @model_validator(mode='after')
    def validate_splits(self):
        if not self.shadow_split + 10 <= self.midtone_split <= self.highlight_split - 10:
            raise ValueError('曲线分界点必须依次递增，且至少相隔 10。')
        return self

class Look(StrictModel):
    contrast: float = Field(default=0, ge=-60, le=60)
    blacks: float = Field(default=0, ge=-60, le=50)
    texture: float = Field(default=0, ge=-30, le=30)
    clarity: float = Field(default=0, ge=-30, le=30)
    dehaze: float = Field(default=0, ge=-20, le=30)
    vibrance: float = Field(default=0, ge=-60, le=60)
    saturation: float = Field(default=0, ge=-60, le=60)
    global_hue: float = Field(default=40, ge=0, le=360)
    global_saturation: float = Field(default=0, ge=0, le=25)
    global_luminance: float = Field(default=0, ge=-100, le=100)
    shadow_hue: float = Field(default=210, ge=0, le=360)
    shadow_saturation: float = Field(default=0, ge=0, le=40)
    shadow_luminance: float = Field(default=0, ge=-100, le=100)
    midtone_hue: float = Field(default=0, ge=0, le=360)
    midtone_saturation: float = Field(default=0, ge=0, le=40)
    midtone_luminance: float = Field(default=0, ge=-100, le=100)
    highlight_hue: float = Field(default=40, ge=0, le=360)
    highlight_saturation: float = Field(default=0, ge=0, le=40)
    highlight_luminance: float = Field(default=0, ge=-100, le=100)
    blending: float = Field(default=50, ge=0, le=100)
    balance: float = Field(default=0, ge=-100, le=100)
    grain: float = Field(default=0, ge=0, le=50)
    vignette: Vignette = Field(default_factory=Vignette)
    colors: list[ColorTarget] = Field(default_factory=list, max_length=8)
    curve: list[CurvePoint] = Field(default_factory=lambda: [CurvePoint(x=0,y=0),CurvePoint(x=255,y=255)], min_length=2, max_length=12)
    red_curve: list[CurvePoint] = Field(default_factory=linear_curve, min_length=2, max_length=12)
    green_curve: list[CurvePoint] = Field(default_factory=linear_curve, min_length=2, max_length=12)
    blue_curve: list[CurvePoint] = Field(default_factory=linear_curve, min_length=2, max_length=12)
    calibration: Calibration = Field(default_factory=Calibration)
    parametric: ParametricCurve = Field(default_factory=ParametricCurve)

    @model_validator(mode='after')
    def validate_curve(self):
        for points in [self.curve,self.red_curve,self.green_curve,self.blue_curve]:
            validate_curve_points(points)
        if len({c.color for c in self.colors}) != len(self.colors):
            raise ValueError('颜色调整不能重复。')
        return self

class LocalAdjustments(StrictModel):
    exposure: float = Field(default=0, ge=-2, le=2)
    contrast: float = Field(default=0, ge=-60, le=60)
    highlights: float = Field(default=0, ge=-100, le=50)
    shadows: float = Field(default=0, ge=-60, le=60)
    whites: float = Field(default=0, ge=-60, le=60)
    blacks: float = Field(default=0, ge=-60, le=60)
    temperature: float = Field(default=0, ge=-60, le=60)
    tint: float = Field(default=0, ge=-40, le=40)
    saturation: float = Field(default=0, ge=-60, le=60)
    clarity: float = Field(default=0, ge=-40, le=40)
    texture: float = Field(default=0, ge=-40, le=40)
    dehaze: float = Field(default=0, ge=-30, le=40)
    blue: float = Field(default=0, ge=0, le=40)

class LocalTarget(StrictModel):
    region_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    reason: str = Field(max_length=500)
    adjustments: LocalAdjustments

class EditingPlan(StrictModel):
    correction: Correction
    look: Look
    local: list[LocalTarget] = Field(default_factory=list, max_length=12)

class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scene: str = Field(max_length=300)
    subject: str = Field(max_length=300)
    composition: str = Field(max_length=800)
    lighting: str = Field(max_length=800)
    mood: str = Field(max_length=300)
    recommended_style: Style
    strategies: list[Strategy] = Field(max_length=6)
    rationale: str = Field(max_length=1500)
    crop_suggestion: str = Field(default='保留原构图', max_length=500)
    editing_plan: EditingPlan | None = None

class SettingsInput(BaseModel):
    base_url: str = 'https://api.deepseek.com'
    model: str = Field(default='deepseek-flash', min_length=1, max_length=100)
    api_key: SecretStr | None = None
    remember_key: bool = False
    clear_key: bool = False

class AnalysisRequest(BaseModel):
    intent: str = Field(default='', max_length=1200)
    auto_correct: bool = False

class RenderRequest(BaseModel):
    style: Style = 'natural'
    strength: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    mode: Literal['photo', 'style'] = 'photo'
    overrides: dict[str, float] = Field(default_factory=dict, max_length=128)
    use_ai: bool = True
    include_local: bool = True
    white_balance: WhiteBalance | None = None
    curve_overrides: dict[Literal['rgb','red','green','blue'], list[CurvePoint]] = Field(default_factory=dict, max_length=4)

    @model_validator(mode='after')
    def validate_curves(self):
        for points in self.curve_overrides.values():
            if not 2 <= len(points) <= 12:
                raise ValueError('每条曲线需要 2–12 个控制点。')
            validate_curve_points(points)
        return self

class ExportRequest(RenderRequest):
    name: str = Field(default='AI RAW Studio', min_length=1, max_length=100)

class RefinementRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=1200)
    state: RenderRequest

class QualityRequest(StrictModel):
    state: RenderRequest
    protect_manual: bool = True

class LocalPatch(StrictModel):
    region_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    reason: str = Field(max_length=500)
    adjustments: dict[str,float] = Field(default_factory=dict, max_length=13)

class Refinement(StrictModel):
    explanation: str = Field(min_length=1, max_length=1500)
    parameters: dict[str,float] = Field(default_factory=dict, max_length=128)
    curves: dict[Literal['rgb','red','green','blue'],list[CurvePoint]] = Field(default_factory=dict, max_length=4)
    local: list[LocalPatch] = Field(default_factory=list, max_length=12)
    white_balance: WhiteBalance | None = None

    @model_validator(mode='after')
    def validate_curves(self):
        RenderRequest(curve_overrides=self.curves)
        if self.white_balance is not None and {'Temperature','Tint'}.intersection(self.parameters):
            raise ValueError('白平衡对象和 Temperature/Tint 参数不能同时修改。')
        return self

class RegionCreate(StrictModel):
    name: str = Field(default='自定义选区', min_length=1, max_length=80)
    bbox: tuple[float,float,float,float] | None = None

class RegionUpdate(StrictModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    adjustments: LocalAdjustments | None = None
    feather: float | None = Field(default=None, ge=0, le=12)

class BrushStroke(StrictModel):
    points: list[tuple[float,float]] = Field(min_length=1, max_length=4000)
    radius: float = Field(ge=.001, le=.2)
    erase: bool = False

    @model_validator(mode='after')
    def validate_points(self):
        if any(not 0 <= v <= 1 for p in self.points for v in p):
            raise ValueError('画笔坐标必须在图像范围内。')
        return self
