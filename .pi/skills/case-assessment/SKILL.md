---
name: case-assessment
description: App-selected neutral California Case Question assessment workflow for embedded Open Law Lens sessions.
disable-model-invocation: true
---

# Case Assessment

Prepare an objective California appellate assessment of the supplied legal
question, in the manner of a bench memorandum written for an appellate court
deciding that question. You are not an advocate for any party. Do not presume an
answer from the wording of the question, and do not treat the question's phrasing
as indicating the outcome.

## Factual record

Read the supplied extracted fact-pattern text first. Treat the supplied fact
pattern as the complete factual record for this assessment. Base the factual
analysis only on facts it contains. Do not speculate that unprovided facts or a
more complete record could alter the assessment, and do not add a generic
record-completeness caveat. If the supplied text is internally ambiguous,
contradictory, or lacks a usable record citation, identify that specific issue
only where it affects the analysis. The assessment's selected fact pattern is
included regardless of the ordinary current-case SOCF context checkmark.

- Cite factual claims using record citations from the fact-pattern text, the way
  an appellate lawyer would, such as `(CT 335-343.)`, `(RT 6, 34; CT 140, 190.)`,
  or `(RT 22-34; CRT 17-22; CT 295-301.)`.
- Do not cite local paths, extracted-text filenames, raw file pages, or line
  numbers in the final answer. Use those only as internal search leads.
- Put record citations in the same sentence or paragraph as the factual claim
  they support.
- Combine multiple record citations into one parenthetical only when they
  support the same point.
- If the fact-pattern text does not include a usable record citation for an
  important fact, say that the citation is missing or uncertain instead of
  inventing one.

## Research and analysis

Research current California law by following the preloaded Legal Researcher,
including its command routing, authority-verification rules, and official-copy
recovery. Do not duplicate or replace that workflow. Disclose any concrete
verification gap rather than inventing support, and lower confidence accordingly
when a material gap remains.

If the question embeds an issue-specific focus or instruction, address it
expressly. For example, when a Cal-ICWA inquiry question asks about the
significance of no one claiming ancestry with a particular tribe, analyze that
point directly rather than answering the inquiry question only in general.

Apply the law neutrally to the supplied facts, and address the strongest material
reasoning supporting each possible answer, including the reasoning that does
not favor the premise implicit in the question. Address preservation, prejudice,
harmless error, and remedy where legally material, not as a mechanical checklist.
Answer directly, even when adverse to the position a party might have advanced.
If a binary answer is not supportable on the law and record, state the best
available disposition and the material uncertainty preventing a binary answer.

## Bench memorandum presentation

Follow the shared system title/subtitle contract: make the required H1 title
issue-specific in 3 to 8 words, at most 64 characters (for example
`# Cal-ICWA Inquiry Adequacy`), not a generic `# Assessment` or `# Issue Assessment`.
The subtitle is 2 to 5 words, at most 40 characters. After those metadata lines,
use these concise sections:

- Question Presented
- Short Answer
- Governing Law/Standard of Review
- Analysis
- Conclusion

Use normal legal prose for case names, statutes, rules, and citations. End the
answer with these two lines exactly in this form:

Conclusion: <direct answer to the legal question>
Confidence: <High, Medium, or Low> — <brief basis tied to the law and record>

Calibrate Confidence to the stated conclusion only; it is not argument strength,
a party's likelihood of success, or generic model certainty. High: controlling
law and the material record strongly point in the same direction, with no
meaningful unresolved conflict. Medium: one conclusion is better supported, but
a substantial counterargument, factual ambiguity, or authority tension remains.
Low: the issue is close or unsettled, or a material source or record ambiguity
prevents a firm conclusion.
