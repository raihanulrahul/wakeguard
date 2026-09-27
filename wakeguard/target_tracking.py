"""Geometry-only continuity for the desk occupant, not identity recognition.

Never switch to the first/largest face while a target is locked. Ambiguity
produces missing target data (and an eventual tracking alert), not someone
else's open eyes. Re-selecting is explicit after a long loss.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FaceBox:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self): return self.w*self.h
    @property
    def center(self): return (self.x+self.w/2,self.y+self.h/2)
    def valid(self):
        return (all(math.isfinite(v) for v in (self.x,self.y,self.w,self.h))
                and .025 <= self.w <= 1.2 and .04 <= self.h <= 1.3
                and -.2 <= self.x <= 1 and -.2 <= self.y <= 1)
    def contains(self,x,y): return self.x<=x<=self.x+self.w and self.y<=y<=self.y+self.h


def score(a,b):
    dx=(a.center[0]-b.center[0])/max(.08,b.w)
    dy=(a.center[1]-b.center[1])/max(.10,b.h)
    return math.hypot(dx,dy)+.45*abs(math.log(a.area/b.area))


class TargetTracker:
    def __init__(self):
        self.anchor=None
        self.last=None
        self.last_seen=None
        self.pending=None
        self.pending_since=0.0
        self.status="select"

    def select(self, boxes, x, y, now):
        choices=[(i,b) for i,b in enumerate(boxes) if b.valid() and b.contains(x,y)]
        if not choices:
            return None
        # Clicking an overlapping face is ambiguous: don't guess a different person.
        if len(choices)>1:
            self.status="ambiguous"
            return None
        i,b=choices[0]
        self.anchor=self.last=b;self.last_seen=now
        self.pending=None;self.status="locked"
        return i

    def update(self, boxes, now):
        choices=[(i,b) for i,b in enumerate(boxes) if b.valid()]
        if self.anchor is None:
            # Auto-select only one dominant foreground face after a short settle.
            choices.sort(key=lambda ib:ib[1].area,reverse=True)
            if not choices or (len(choices)>1 and choices[0][1].area < 1.8*choices[1][1].area):
                self.pending=None;self.status="select" if not choices else "ambiguous"
                return None
            i,b=choices[0]
            if self.pending is None or score(b,self.pending)>.4:
                self.pending=b;self.pending_since=now
            if now-self.pending_since<.6:
                self.status="acquiring";return None
            self.anchor=self.last=b;self.last_seen=now
            self.pending=None;self.status="locked";return i
        if self.last_seen is None or now-self.last_seen>2.0:
            similar=[(i,b) for i,b in choices if .55<=b.area/self.anchor.area<=1.8 and score(b,self.anchor)<.65]
            if len(similar)!=1:
                self.pending=None;self.status="reselect";return None
            i,b=similar[0]
            if self.pending is None or score(b,self.pending)>.25:
                self.pending=b;self.pending_since=now
            if now-self.pending_since<.8:
                self.status="reacquiring";return None
            self.last=b;self.last_seen=now;self.pending=None;self.status="locked";return i
        # Whole-person translation and recline are allowed. Sudden box swaps,
        # distant passers and two equally plausible candidates are not.
        viable=[]
        for i,b in choices:
            ratio=b.area/self.last.area
            anchor_ratio=b.area/self.anchor.area
            if not .65<=ratio<=1.55 or not .22<=anchor_ratio<=3.0:
                continue
            distance=score(b,self.last)
            if distance<=.85:
                viable.append((distance,i,b))
        viable.sort(key=lambda x:x[0])
        if not viable or (len(viable)>1 and viable[1][0]-viable[0][0]<.35):
            self.status="lost" if not viable else "ambiguous"
            return None
        _,i,b=viable[0]
        self.last=b;self.last_seen=now;self.status="locked"
        return i
