# Security policy

incognito-sql keeps personal values away from an LLM agent. A way around that is a
vulnerability, and we want to hear about it before anyone else does.

## What counts

- Any path by which a value of an identifier, secret, free-text or undeclared column
  reaches the model: an answer, an error, the tool listing, `describe`, timing beyond what
  the threat model (`docs/threat-model.md`) names, or anything else the model can read.
- A masked open cell whose value reaches the model.
- The card web showing a value without a session, or to a host other than `127.0.0.1`.
- A token store or audit log readable or writable by a user it was not created for.

The limits listed under "What it does not protect against" in
[docs/threat-model.md](docs/threat-model.md) are known. A new
way to exploit one of them more than it says is in scope.

## How to report

E-mail **khodossss@gmail.com** with the subject `incognito-sql security`, or use GitHub's
private vulnerability reporting on this repository. Please do not open a public issue.

Include the version (`pip show incognito-sql`, or the commit), the DBMS, the relevant part
of the field declaration, and the SQL or steps that show the value. Invented data only,
please: never send real personal data.

## What happens next

You get a reply, a fix in a patch release, and credit in the release notes unless you ask
otherwise. Only the latest release is fixed.
