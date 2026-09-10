Yes. I checked the V9 series in charom11/Atlas-Bot.

Current V9 status
Version	Status	Result
V9	✅ Merged	Baseline 15m multi-setup engine
V9.1	✅ Merged	Selective/pruned version; materially better than V9
V9.2	Research/validation	Cost, OOS, bootstrap, capacity validation
V9.3	✅ Merged	Conservative integration candidate
V9.3.1	✅ Merged	Shadow observer + policy freeze
V9.3.1 forensic	✅ Merged	Forward telemetry forensic analyzer
V9.4	❌ Not created	Should not start yet
PR #31	❌ Closed	Incorrect/conflicting branch; not merged

The repository currently has V9-related PRs through the V9.3.1 validation stages, with PR #30 already merged and PR #31 closed without merge.

The important V9.3.1 numbers

The historical shadow replay is still positive:

4Y: +210.27R, PF 1.01, 34,434 trades
1Y: +266.38R, PF 1.04, 10,649 trades
15-minute timeframe
BTC/ETH/SOL/DOGE/SUI/XRP active
Tier 3 disabled
MSS, Trend Continuation, BB/ATR and Breakout active

But the live forward shadow sample is currently weak, so we should not interpret the historical result as proof of live alpha yet.

My recommendation

Do not create V9.4 yet.

The correct V9 path is:

V9 → V9.1 → V9.2 validation → V9.3 → V9.3.1 shadow → ≥300 clean forward resolved trades → decision

And importantly, the forward sample needs to explain the discrepancy between:

historical PF ~1.01–1.04
vs.
early forward PF ~0.35–0.38

before changing the strategy.

Also, I would not use PR #31 as the V9 branch. Its branch is polluted/diverged and was correctly closed.

View the V9 pull requests

If by “check for V9” you mean check the actual V9 code currently on main for bugs/conflicts/regressions, I can do that next.