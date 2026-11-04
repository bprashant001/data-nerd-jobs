# Data Nerd feeds

Two public feeds for the
[Data Nerd](https://play.google.com/store/apps/details?id=com.mangopickle.datanerd) app,
rebuilt by GitHub Actions:

- [`jobs.json`](https://bprashant001.github.io/data-nerd-jobs/jobs.json): data
  engineering roles for the Jobs tab, every morning.
- [`news.json`](https://bprashant001.github.io/data-nerd-jobs/news.json): data and
  AI industry updates for the News tab, every three hours.

## News sources

`news/sources.yaml` lists them: first-party feeds that companies and labs
publish for syndication (Databricks, Snowflake, dbt Labs, Confluent, AWS,
Google Cloud, Azure, Apache, OpenAI, Google AI, Google DeepMind, Hugging Face)
and Hacker News's official search API. Only the publisher's headline and its
own short excerpt are kept, every item links to the original story, and each
request is checked against the site's `robots.txt`. General press outlets are
not used, because their feed terms limit reuse to personal reading.

## Where the jobs come from

Only data that employers and job boards publish for reuse:

- **Public job-board APIs** of applicant tracking systems that employers use
  to list their openings: Greenhouse, Lever, Ashby, SmartRecruiters, Workable.
- **Workday career sites**: one "data engineer" search per site per day
  through the same endpoint the public careers page uses, plus the
  schema.org `JobPosting` data on a few matching job pages. Every request is
  checked against the site's `robots.txt` first, and requests are paced.
- **Arbeitnow**'s free job-board API (Europe).
- Optionally **Adzuna**, when API keys are configured.

The feed keeps a title, company, location, level, skill tags and a short
summary. Applicants are always sent to the original posting.

Not used: LinkedIn, Naukri, Indeed or any site whose terms or `robots.txt`
forbid automated access.

## Opting out

If you represent a company or publication listed here and would like it
removed, open an issue or email mangopickle909@gmail.com and it will be removed
from `jobs/companies.yaml` or `news/sources.yaml`.

## Layout

```
jobs/companies_source.csv   Companies that commonly hire data engineers
jobs/companies.yaml         Their public job boards (generated, then curated)
tools/jobs/                 Discovery, fetching and classification scripts
news/sources.yaml           News feeds
tools/news/                 News fetcher and its tests
docs/                       Published feed (GitHub Pages)
```

```bash
python tools/jobs/fetch_jobs.py --out docs
```

```bash
python -m unittest discover -s tools/jobs
```
