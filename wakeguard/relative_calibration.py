"""Build usable channels, not an all-or-nothing generic-head-model exam."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from .model import Profile, SCHEMA, finite, median, scene_distance
from .face_context import valid_shape, neck_separation, delta_shape


def _attach_glasses(session, profile, screen_pairs, summarize, view_clusters, CalibrationError, partial=False):
    """Attach glasses-on eye references plus a personalized on/off classifier.

    Glasses enrollment is a compatibility measurement, not another pass/fail
    posture exam. A screen whose eyelids are genuinely hidden is recorded as
    eye-unobservable and monitoring falls back to posture/activity there.
    """
    from .glasses import build_prototype, prototype_separation, AUTO_MIN_SEPARATION
    if not getattr(session, "glasses_enabled", False):
        profile.report["glasses"] = {"enabled": False}
        return
    open_views, closed_views, masks, pairs = [], [], [], []
    coverage, eye_support = {}, {}
    for index, off_open, _, _ in screen_pairs:
        on_open = session.glasses_open_samples.get(index, [])
        on_closed = session.glasses_closed_samples.get(index, [])
        targets = [("glasses_on_open", index), ("glasses_on_closed", index)]
        if not on_open or not on_closed:
            if partial:
                continue
            raise CalibrationError(f"Glasses screen {index+1}: open/closed compatibility captures are missing.", targets)
        a,b = summarize(on_open),summarize(on_closed)
        if not valid_shape(a.get("shape")) or not valid_shape(b.get("shape")) or Profile.view_distance(a,b) > 35:
            raise CalibrationError(f"Glasses screen {index+1}: the face context changed too much between the two short takes. Repeat only this screen pair.", targets)
        usable=[]
        for side in ("left","right"):
            if not finite(a.get(side)) or not finite(b.get(side)):
                continue
            gap=a[side]-b[side]
            noise=max(a.get(side+"_spread") or 0,b.get(side+"_spread") or 0)
            if gap >= max(.035,3*noise):
                usable.append(side)
        eye_support[str(index+1)] = list(usable)
        if usable:
            for view in view_clusters(on_open):
                for side in ("left","right"):
                    if side not in usable: view[side]=None
                view["screen"]=index+1;open_views.append(view)
            for view in view_clusters(on_closed):
                for side in ("left","right"):
                    if side not in usable: view[side]=None
                view["screen"]=index+1;closed_views.append(view)
            masks.append({"shape":a["shape"],"sides":usable,"screen":index+1})
        off_proto=build_prototype(off_open);on_proto=build_prototype(on_open)
        separation=prototype_separation(off_proto,on_proto) if off_proto and on_proto else 0.0
        pairs.append({"screen":index+1,"shape":a["shape"],"off":off_proto,"on":on_proto,
                      "separation":separation,"auto_ok":bool(off_proto and on_proto and separation>=AUTO_MIN_SEPARATION)})
    profile.report["glasses"]={"enabled":True,"open_views":open_views,"closed_views":closed_views,
                               "view_masks":masks,"pairs":pairs,
                               "eye_supported":bool(open_views and closed_views),
                               "eye_screen_support":eye_support,
                               "auto_available":bool(pairs) and all(p["auto_ok"] for p in pairs),
                               "auto_partial":any(p["auto_ok"] for p in pairs),
                               "coverage":coverage,
                               "notes":"Personalized numeric glasses cues; manual On/Off always overrides Auto. Eye-hidden screens use posture/activity support."}
    for index,on_open in sorted(session.glasses_open_samples.items()):
        sides=eye_support.get(str(index+1),[])
        if not sides:
            coverage[str(index+1)]={"open":0.0,"closed":0.0,"eye_observable":False}
            continue
        on_closed=session.glasses_closed_samples.get(index, [])
        if not on_closed:
            continue
        open_good=sum(bool(r) and min(r)>=.70 for o in on_open if (r:=profile.eye_ratios(o,glasses_state="on")) is not None)/len(on_open)
        closed_good=sum(bool(r) and min(r)<.35 for o in on_closed if (r:=profile.eye_ratios(o,glasses_state="on")) is not None)/len(on_closed)
        coverage[str(index+1)]={"open":open_good,"closed":closed_good,"eye_observable":min(open_good,closed_good)>=.65}
        if min(open_good,closed_good)<.65:
            # The raw side looked separable but runtime matching is not stable.
            eye_support[str(index+1)]=[]
            coverage[str(index+1)]["eye_observable"]=False
            profile.report["glasses"]["open_views"]=[v for v in profile.report["glasses"]["open_views"] if v.get("screen") != index+1]
            profile.report["glasses"]["closed_views"]=[v for v in profile.report["glasses"]["closed_views"] if v.get("screen") != index+1]
            profile.report["glasses"]["view_masks"]=[v for v in profile.report["glasses"]["view_masks"] if v.get("screen", index+1) != index+1]
    profile.report["glasses"]["eye_supported"] = bool(profile.report["glasses"]["open_views"] and profile.report["glasses"]["closed_views"])


def build_relative(session, partial=False):
    # Imported here to avoid a module cycle with CalibrationSession.build().
    from .calibration import CalibrationError, summarize, view_clusters
    reports = {k: summarize(v) for k, v in session.samples.items()}
    keys = {o.camera_key for values in session.samples.values() for o in values}
    if len(keys) != 1 or not next(iter(keys)):
        raise CalibrationError("Camera changed during collection. Start a new camera setup; old references are preserved.")
    notes = []
    channels = {"eyes": True, "recline": False, "neck_down": False, "neck_up": False}
    opens, closes = [], []
    screen_pairs = []
    # Each actual work screen has matching OPEN and CLOSED captures. Do not
    # force generic left/right poses to substitute for a user's real monitor.
    for index in range(session.monitor_count):
        op = session.monitor_samples.get(index, session.samples.get("main", []) if index == 0 else [])
        cl = session.closed_monitor_samples.get(index, session.samples.get("closed_main", []) if index == 0 else [])
        targets = [("monitors", index), ("closed_main", index)]
        if not op or not cl:
            if partial:
                continue
            raise CalibrationError(f"Work screen {index+1}: matching open/closed eye observations are still needed.", targets)
        if not all(valid_shape(o.shape) for o in op+cl):
            raise CalibrationError(f"Work screen {index+1}: mixed measurement methods. Repeat this screen pair.", targets)
        a,b = summarize(op),summarize(cl)
        if Profile.view_distance(a,b) > 35:
            raise CalibrationError(f"Work screen {index+1}: open and closed captures describe different camera views. Repeat only this screen pair.", targets)
        usable = []
        for side in ("left", "right"):
            if not finite(a.get(side)) or not finite(b.get(side)):
                continue
            gap = a[side]-b[side]
            noise = max(a.get(side+"_spread") or 0, b.get(side+"_spread") or 0)
            if gap >= max(.035, 3*noise):
                usable.append(side)
        if not usable:
            raise CalibrationError(f"Work screen {index+1}: the camera could not distinguish open from closed eyelids. This is a sensor limitation, not a posture failure.", targets)
        screen_pairs.append((index,op,cl,usable))
        for view in view_clusters(op):
            for side in ("left","right"):
                if side not in usable:
                    view[side] = None
            view["screen"] = index+1
            opens.append(view)
        for view in view_clusters(cl):
            for side in ("left","right"):
                if side not in usable:
                    view[side] = None
            view["screen"] = index+1
            closes.append(view)
    # Additional awake contexts are useful only if a measured CLOSED reference
    # supports them. One poor eye is excluded rather than vetoing the good eye.
    optional_opens = []
    for key in ("main", "left", "right", "reading", "reclined", "neck_down", "neck_up"):
        optional_opens.extend(view_clusters(session.samples.get(key, [])))
    optional_closes = []
    for key in ("closed_left", "closed_right", "closed_reclined"):
        optional_closes.extend(view_clusters(session.samples.get(key, [])))
    closes.extend(optional_closes)
    def accepted_open(view):
        if not valid_shape(view.get("shape")):
            return False
        for side in ("left","right"):
            choices = [c for c in closes if finite(c.get(side))]
            if not finite(view.get(side)) or not choices:
                view[side] = None
                continue
            ref = min(choices, key=lambda c: Profile.view_distance(view,c))
            noise = max(view.get(side+"_spread") or 0, ref.get(side+"_spread") or 0)
            if Profile.view_distance(view,ref)>35 or view[side]-ref[side]<max(.035,3*noise):
                view[side] = None
        return any(finite(view.get(side)) for side in ("left","right"))
    opens = [v for v in opens+optional_opens if accepted_open(v)]
    if not opens or not closes:
        raise CalibrationError("The camera has not provided distinguishable open/closed eye references.")

    neutral = reports.get("main", {})
    if not valid_shape(neutral.get("shape")):
        raise CalibrationError("No usable normal-work geometry was collected.")
    reclined = reports.get("reclined", {})
    down,up = reports.get("neck_down", {}),reports.get("neck_up", {})
    normal_views = [v for k in ("main", "left", "right", "reading", "monitors")
                    for v in view_clusters(session.samples.get(k, []))]
    if not normal_views:
        normal_views = [neutral]
    def captured(key):
        return bool(session.samples.get(key)) and not session.capture_reports.get(key,{}).get("unavailable")
    if captured("reclined") and finite(reclined.get("area")) and reclined["area"]>0:
        separation=math.hypot(math.log(reclined["area"]/neutral["area"])/.15,(reclined["cy"]-neutral["cy"])/.04)
        channels["recline"] = separation>=1
    for name,ref in (("neck_down",down),("neck_up",up)):
        channels[name] = captured(name) and neck_separation(neutral,ref)>=.65
    if channels["neck_down"] and channels["neck_up"]:
        da,ua=delta_shape(down["shape"],neutral["shape"]),delta_shape(up["shape"],neutral["shape"])
        if sum(da[i]*ua[i] for i in (1,2))>=0:
            channels["neck_down"]=channels["neck_up"]=False
    for key in ("recline","neck_down","neck_up"):
        if not channels[key]:
            notes.append(f"{key.replace('_',' ')} support unavailable; eye monitoring remains independent")

    empty=session.samples.get("empty",[])
    signature=[];tolerance=.008;automatic_away=False
    if empty and all(len(o.scene)==len(empty[0].scene) and o.scene for o in empty):
        signature=[median([o.scene[i] for o in empty]) for i in range(len(empty[0].scene))]
        distances=[scene_distance(o.scene,signature) for o in empty]
        tolerance=min(.045,max(.008,max(distances)*1.5+.005))
        occupied=median([scene_distance(o.scene,signature) for o in session.samples["main"]])
        automatic_away=occupied>tolerance*1.6
    if not automatic_away:
        notes.append("Automatic empty-chair detection unavailable; use Leaving seat. A missing face alone never means away.")
    report={"valid":True,"context_method":"face-relative-v1","channels":channels,
            "stages":reports,"normal_views":normal_views,"monitor_count":session.monitor_count,
            "capture_quality":session.capture_reports,"auto_away_enabled":automatic_away,
            "reclined_eyes_valid":True,"half_thresholds":{},"notes":notes,
            "view_masks":[{"shape":summarize(op)["shape"],"sides":sides} for _,op,_,sides in screen_pairs]}
    brightness=median([o.brightness for _,op,_,_ in screen_pairs for o in op])
    profile=Profile(SCHEMA,next(iter(keys)),datetime.now(timezone.utc).isoformat(),opens,closes,
                    neutral,reclined,down,up,signature,tolerance,brightness,report)
    recline_closed = reports.get("closed_reclined", {})
    report["reclined_eyes_valid"] = any(
        finite(reclined.get(side)) and finite(recline_closed.get(side))
        and reclined[side] - recline_closed[side] >= .035
        for side in ("left", "right"))
    # Half-closed is subjective: learn a usable sample, never demand a precise
    # eyelid pose. Otherwise retain the existing conservative partial threshold.
    for key,location in (("half_upright","upright"),("half_reclined","reclined")):
        ratios=[min(rs) for o in session.samples.get(key,[]) if (rs:=profile.eye_ratios(o))]
        if ratios and .12 < median(ratios) < .80:
            report["half_thresholds"][location]=min(.8,max(.6,median(ratios)+.08))
        else:
            notes.append(f"No distinct {location} half-eye anchor; default partial-eye sensitivity retained")
    # Verify both labelled states, not merely that references exist. A side
    # screen cannot borrow another screen's normal values silently.
    coverage={}
    for index,op,cl,_ in screen_pairs:
        open_match=sum(bool(rs) and min(rs)>=.70 for o in op if (rs:=profile.eye_ratios(o)) is not None)/len(op)
        closed_match=sum(bool(rs) and min(rs)<.35 for o in cl if (rs:=profile.eye_ratios(o)) is not None)/len(cl)
        coverage[str(index+1)]={"open":open_match,"closed":closed_match}
        if min(open_match,closed_match)<.65:
            raise CalibrationError(f"Work screen {index+1}: the camera's eye observations are not separable across normal motion. Repeat this screen's open/closed pair, not all postures.", [("monitors", index), ("closed_main", index)])
    report["monitor_reference_coverage"]=coverage
    _attach_glasses(session, profile, screen_pairs, summarize, view_clusters, CalibrationError, partial=partial)
    profile.validate()
    return profile
