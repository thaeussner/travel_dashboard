"""Emission profiles: mode defaults and specific vehicles from config/emissions.toml.

A number in the config is either fixed or a [low, central, high] triple, which the Monte Carlo
samples as a triangular distribution. Each parameter is drawn once per draw and shared by every
travel that uses it (one TGV factor for all TGV legs, one non-CO2 multiplier for all flights), so
totals and differences get honest intervals.
"""

from __future__ import annotations

import random
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .tables import Travel

META_KEYS = {"kind", "label", "grade", "source", "match", "name", "mode", "fuel", "note"}
Spec = float | int | list


def central(spec: Spec) -> float:
    return float(spec[1]) if isinstance(spec, list) else float(spec)


class Sampler:
    """Parameter values for one Monte Carlo draw. rng=None gives central values (for traces)."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng
        self.cache: dict[tuple, float] = {}

    def new_draw(self) -> None:
        self.cache.clear()

    def get(self, path: tuple, spec: Spec) -> float:
        if not isinstance(spec, list):
            return float(spec)
        if self.rng is None:
            return float(spec[1])
        v = self.cache.get(path)
        if v is None:
            lo, mode, hi = (float(x) for x in spec)
            v = self.rng.triangular(lo, hi, mode) if hi > lo else mode
            self.cache[path] = v
        return v


@dataclass
class Profile:
    """Parameters resolved for one travel row: mode defaults, overlaid with a matched vehicle."""

    mode: str
    kind: str
    label: str
    grade: str
    params: dict[str, tuple[tuple, Spec]]
    sources: list[str]
    vehicle: str | None = None       # name of the matched vehicle profile
    flight_class: str | None = None

    def has(self, key: str) -> bool:
        return key in self.params

    def get(self, key: str, s: Sampler) -> float:
        path, spec = self.params[key]
        return s.get(path, spec)

    def spec(self, key: str) -> Spec:
        return self.params[key][1]


class Profiles:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.fuels: dict = cfg["fuels"]
        self.flight: dict = cfg["flight"]
        self.alloc: dict = cfg["allocation"]
        self.modes: dict = cfg["modes"]
        self.vehicles: list[dict] = cfg.get("vehicles", [])
        self._veh = [(v, [_word(p) for p in v.get("match", [])]) for v in self.vehicles]
        self._fc = {k: [_word(p) for p in v.get("match", [])]
                    for k, v in self.flight.items() if isinstance(v, dict)}
        self.cars: dict = cfg.get("cars", {})
        self._car_sizes = [(n, [_word(p) for p in pats]) for n, pats in self.cars.get("sizes", {}).items()]
        self._car_fuels = [(n, [_word(p) for p in pats]) for n, pats in self.cars.get("fuels", {}).items()]

    @classmethod
    def load(cls, path: Path) -> Profiles:
        return cls(tomllib.loads(path.read_text(encoding="utf-8")))

    @property
    def version(self) -> str:
        return str(self.cfg.get("meta", {}).get("version", ""))

    def match_vehicle(self, mode: str, text: str) -> dict | None:
        if not text:
            return None
        for v, pats in self._veh:
            if v.get("mode", mode) != mode:
                continue
            if any(p.search(text) for p in pats):
                return v
        return None

    def car_class(self, text: str) -> tuple[str, str]:
        """(size, fuel) read from a car's vehicle text, e.g. 'Citroën C1 (95)' → ('small', 'petrol')."""
        size = next((n for n, pats in self._car_sizes if any(p.search(text) for p in pats)),
                    self.cars.get("size_default", "average"))
        fuel = next((n for n, pats in self._car_fuels if any(p.search(text) for p in pats)),
                    self.cars.get("fuel_default", "petrol"))
        return size, fuel

    def flight_class(self, t: Travel) -> str:
        for cls in ("turboprop", "wide", "narrow"):
            if any(p.search(t.vehicle) for p in self._fc.get(cls, [])):
                return cls
        return "wide" if t.km >= self.flight["wide_from_km"] else "narrow"

    def resolve(self, t: Travel) -> Profile:
        base = self.modes[t.mode]
        kind = base["kind"]
        params: dict[str, tuple[tuple, Spec]] = {
            k: (("modes", t.mode, k), v) for k, v in base.items() if k not in META_KEYS}
        sources = [base["source"]] if base.get("source") else []
        label, grade, fuel = base.get("label", t.mode), base.get("grade", "D"), base.get("fuel")
        veh = self.match_vehicle(t.mode, t.vehicle)
        if veh:
            for k, v in veh.items():
                if k not in META_KEYS:
                    params[k] = (("vehicle", veh["name"], k), v)
            label, grade = veh["name"], veh.get("grade", grade)
            fuel = veh.get("fuel", fuel)
            if veh.get("source"):
                sources.insert(0, veh["source"])
        if t.mode == "car" and not veh and self.cars.get("g_vkm"):
            size, kind_ = self.car_class(t.vehicle)
            table = self.cars["g_vkm"]
            key = next(k for k in (f"{size}_{kind_}", f"average_{kind_}", "average_petrol") if k in table)
            params["g_vkm"] = (("cars", key), table[key])
            label, grade = f"{key.replace('_', ' ')} car", "C"
            fuel = {"diesel": "diesel", "electric": None}.get(kind_, "petrol")   # factor for logged litres
            if self.cars.get("source"):
                sources.insert(0, self.cars["source"])
        fclass = None
        if kind == "flight":
            fclass = self.flight_class(t)
            for k, v in self.flight[fclass].items():
                if k not in META_KEYS:
                    params.setdefault(k, (("flight", fclass, k), v))
            for k in ("uplift", "co2_per_kg"):
                params[k] = (("flight", k), self.flight[k])
            nk = ("nonco2_turboprop" if fclass == "turboprop"
                  else "nonco2_short" if t.km < self.flight["short_km"] else "nonco2_long")
            params["nonco2"] = (("flight", nk), self.flight[nk])
            params["wtt"] = (("fuels", "jet_wtt"), self.fuels["jet_wtt"])
            label = f"{label} · {self.flight[fclass].get('label', fclass)}" if veh else self.flight[fclass].get("label", fclass)
            if self.flight.get("source"):
                sources.append(self.flight["source"])
        if fuel:
            params["fuel_factor"] = (("fuels", fuel), self.fuels[fuel])
        if kind == "ship":
            for k, v in self.alloc.items():
                if k not in META_KEYS:
                    params[k] = (("allocation", k), v)
            if self.alloc.get("source"):
                sources.append(self.alloc["source"])
        if kind in ("fuel", "vehicle") and t.fuel_l and "fuel_factor" in params:
            grade = "A"
        return Profile(t.mode, kind, label, grade, params, sources, veh["name"] if veh else None, fclass)


def _word(pattern: str) -> re.Pattern:
    """Match a config keyword as a whole word, case-insensitive ('ter' must not match 'Tenerife')."""
    return re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", re.I)
