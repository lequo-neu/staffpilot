# Case rules

Source: IE5374 Module 7 Hackathon brief, Topic 3, Dynamic Agent Staffing Optimization, a problem contributed by Google.

## Goal

Decide how many support agents each country needs in each month of the planning year. Balance cost efficiency (few idle agents), timely support (short waits, more revenue uplift) and scalability (adjusting to demand swings within the hiring and firing rules).

## Eligibility

When an advertiser signs up, Google projects its annual advertising budget. If the projected budget exceeds the country threshold, the advertiser is eligible for agent support. Otherwise it is ineligible and receives no agent.

## Waiting pool

Eligible advertisers enter a waiting pool. If an agent has a free slot, the advertiser is assigned at once. If no slot is free, the advertiser waits in the pool for up to 60 days. An advertiser still unassigned after 60 days is removed from the pool and never receives support.

## Agent capacity

Each agent supports at most 10 advertisers at the same time. Staffing is local: agents only serve advertisers from their own country.

## Support length

Each assigned advertiser receives support for 60 days and then graduates, which frees the slot for the next advertiser. All agents start the planning year with no advertisers assigned.

## Hiring

A new agent needs one month of ramp up before taking advertisers. An agent hired in a month can work from the following month.

## Firing

Releasing an agent requires one month of advance notice and costs 40 percent of the agent's annual salary.

## Revenue uplift

Agent support raises the advertiser's ad spend. The uplift is random: 0 percent with probability 5 percent, 5 percent with probability 15 percent, 10 percent with probability 25 percent, 15 percent with probability 25 percent, 20 percent with probability 20 percent and 25 percent with probability 10 percent. The expected uplift is 13.5 percent.

## Data

The teaching team provides annual agent salary per country, the eligibility threshold per country, one row per advertiser sign up over two years (advertiser id, country, sign up date, projected annual budget) and the agent headcount per country in January of the planning year.
