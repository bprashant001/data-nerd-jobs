# Data Nerd jobs feed

The daily list of data engineering roles shown in the
[Data Nerd](https://play.google.com/store/apps/details?id=com.mangopickle.datanerd)
app's Jobs tab. A GitHub Action rebuilds it every morning and publishes
[`jobs.json`](https://bprashant001.github.io/data-nerd-jobs/jobs.json).

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

If you represent a company listed here and would like it removed, open an
issue or email mangopickle909@gmail.com and it will be removed from
`jobs/companies.yaml`.

## Layout

```
jobs/companies_source.csv   Companies that commonly hire data engineers
jobs/companies.yaml         Their public job boards (generated, then curated)
tools/jobs/                 Discovery, fetching and classification scripts
docs/                       Published feed (GitHub Pages)
```

```bash
python tools/jobs/fetch_jobs.py --out docs
```

```bash
python -m unittest discover -s tools/jobs
```
