"""User-randomized synthetic experiment, separate from the observational fixture."""
import math
import random
from scipy.stats import binomtest, norm


def sample_size(p=.10, mde=.015, alpha=.05, power=.8):
    """Normal approximation, equal arms, two-sided test; absolute MDE."""
    q = p+mde
    if not 0 < p < q < 1:
        raise ValueError("Require 0 < p < p+mde < 1")
    pooled = (p+q)/2
    numerator = norm.ppf(1-alpha/2)*math.sqrt(2*pooled*(1-pooled)) + norm.ppf(power)*math.sqrt(p*(1-p)+q*(1-q))
    return math.ceil(numerator**2/mde**2)


def difference(a_success, a_n, b_success, b_n, alpha=.05):
    if min(a_n,b_n)<=0 or not (0<=a_success<=a_n and 0<=b_success<=b_n):
        raise ValueError("Invalid binomial counts")
    pa,pb = a_success/a_n,b_success/b_n
    effect = pb-pa
    se = math.sqrt(pa*(1-pa)/a_n+pb*(1-pb)/b_n)
    pooled = (a_success+b_success)/(a_n+b_n)
    null_se = math.sqrt(pooled*(1-pooled)*(1/a_n+1/b_n))
    pvalue = float(2*norm.sf(abs(effect/null_se))) if null_se else 1.
    z = float(norm.ppf(1-alpha/2))
    return {"a_rate":pa,"b_rate":pb,"absolute_effect":effect,
            "ci95":[effect-z*se,effect+z*se],"p_value":pvalue,
            "method":"pooled two-sided z test; unpooled normal difference CI"}


def run_experiment(seed=20261021, n=20000, skew=False):
    rng = random.Random(seed)
    groups = {v:{"n":0,"converted":0,"refunded_users":0,"segments":{}} for v in ["A","B"]}
    for _ in range(n):
        channel = rng.choice(["organic","paid"])
        v = "B" if rng.random() < (.6 if skew else .5) else "A"
        p = (.14 if channel=="organic" else .06) + (.015 if v=="B" else 0)
        converted = int(rng.random()<p)
        # B improves conversion but introduces a deliberately harmful refund mechanism.
        refund = int(converted and rng.random() < (.13 if v=="B" else .03))
        g=groups[v]
        g["n"]+=1; g["converted"]+=converted; g["refunded_users"]+=refund
        s=g["segments"].setdefault(channel,{"n":0,"converted":0})
        s["n"]+=1; s["converted"]+=converted
    a,b=groups["A"],groups["B"]
    srm=float(binomtest(b["n"],n,.5).pvalue)
    primary=difference(a["converted"],a["n"],b["converted"],b["n"])
    guardrail=difference(a["refunded_users"],a["n"],b["refunded_users"],b["n"])
    segments={c:difference(a["segments"][c]["converted"],a["segments"][c]["n"],b["segments"][c]["converted"],b["segments"][c]["n"]) for c in ["organic","paid"]}
    harmful=guardrail["ci95"][0]>.002
    decision="hold_invalid_assignment" if srm<.001 else ("hold_guardrail_harm" if harmful else "review_primary_and_guardrail_uncertainty")
    return {"synthetic":True,"seed":seed,"randomization_unit":"user","planned_n_per_arm":sample_size(),
            "groups":groups,"srm_p_value":srm,"srm_threshold":.001,"primary":primary,
            "guardrail_refunded_users_per_assigned_user":guardrail,
            "guardrail_max_absolute_increase":.002,"segments_exploratory":segments,
            "decision":decision,"limitations":["Synthetic experiment; no actual business lift.","Normal approximation is suitable only for sufficiently populated cells.","Segment analyses are exploratory, not additional confirmatory tests.","Refund window is complete by construction; real data requires a fixed maturity window."]}
