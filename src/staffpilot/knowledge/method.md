# How the plan is built

## Forecast

Monthly eligible sign ups per country are forecast with simple seasonal methods. The method is chosen by a backtest that trains on the earlier year and predicts the last history year. With only two years, the seasonal mean of both years is used when methods tie, because it uses the most data.

## Optimizer

A mixed integer program is solved for every country. Headcount decisions (hires and notices) are monthly. Advertiser flows are weekly: a started advertiser occupies a slot for nine weeks, which covers the 60 day support period, and may wait up to eight weeks. Capacity is checked in every month a week touches, which keeps the plan feasible when headcount is cut. The objective is expected uplift value minus salary and firing cost. A service level variant adds a floor on the share of eligible advertisers served.

## Simulator

A day by day simulator applies the rules exactly: graduation after 60 days, the 60 day waiting limit, ten advertisers per agent and the monthly headcount from the plan. A slot counts as free only if it exists for the whole support period under the plan, so an agent under notice takes no new advertisers and the limit of ten holds on every day. All reported numbers come from the simulator. When a plan must meet a service floor and the simulator falls short, the optimizer is rerun with a higher minimum headcount in the months that lost advertisers.

## Baselines

Three simple policies are compared with the optimized plan: keeping January headcount all year, matching last month's demand, and a single cut to the yearly peak plus 10 percent.

## Uncertainty

Monte Carlo runs resample daily sign ups from the same calendar month in history, which keeps the large day to day noise, and draw each advertiser's uplift from the brief distribution. Sensitivity runs scale sign ups from 70 to 130 percent and compare keeping the current plan with replanning.
