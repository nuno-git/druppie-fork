---
name: data-analysis-plan
description: >
  Format template for docs/data-analysis-plan.md. Use this skill when writing
  data analysis plan during data_analyst phase.
---

# Data Analysis Plan

## Introduction

### Subject
[Brief description of the data question/problem]

### Original Question
[The original question from the user in natural language]

### Clarified Question
[The fully understood question with additional clarifications]

### Business Context
[Why is this question important? What is the goal of the analysis?]

### Success Criteria
[When is this analysis successfully answered?]

## Scope

### In Scope
- [Which datasets will be used]
- [Which analysis types will be applied]
- [Which time period will be covered]
- [Which specific metrics/KPIs]

### Out of Scope
- [What falls outside this analysis]
- [Which datasets are explicitly not used]
- [Which analysis types are not applied]

## Requirements

### Functional Requirements
| ID | Requirement | Source | Verification |
|----|-------------|--------|---------------|
| FR-01 | [Specific functional requirement] | [User/BA] | [Test] |
| FR-02 | [Specific functional requirement] | [User/BA] | [Test] |

### Non-Functional Requirements
| ID | Requirement | Priority | Verification |
|----|-------------|-----------|---------------|
| NFR-01 | [Performance requirement e.g., < 30 seconds] | High | [Test] |
| NFR-02 | [Data quality requirement] | Medium | [Check] |

### Acceptance Criteria (AC)
| ID | AC Description | Test Scenario |
|----|----------------|---------------|
| AC-01 | [Specific criteria that must be met] | [How to test] |
| AC-02 | [Specific criteria that must be met] | [How to test] |

## Dataset Analysis & Selection

### Available Datasets
| # | Dataset Name | Description | Data Type | Availability | Quality | Primary Keys |
|---|---------------|-------------|------------|-----------------|-----------|----------------|
| 1 | [Name] | [Short description] | [Structured/Unstructured] | [Yes/No] | [High/Medium/Low] | [Key columns] |
| 2 | [Name] | [Short description] | [Structured/Unstructured] | [Yes/No] | [High/Medium/Low] | [Key columns] |

### Selected Datasets
| Dataset | Relevance Score | Reason for Selection | Data Gaps | Mitigation |
|----------|-----------------|---------------------|------------|-----------|
| [Dataset 1] | [1-10] | [Why relevant] | [What's missing] | [How to solve] |

### Data Join Strategy (REQUIRED when combining multiple datasets)
| Join # | Left Dataset | Right Dataset | Join Type | Join Key(s) | Join Logic | Reason for Join |
|--------|--------------|---------------|------------|-------------|------------|-----------------|
| 1 | [Dataset A] | [Dataset B] | [INNER/LEFT/RIGHT/FULL] | [key_a = key_b] | [Business logic] | [Why combine] |
| 2 | [Join 1 Result] | [Dataset C] | [INNER/LEFT/RIGHT/FULL] | [key_ab = key_c] | [Business logic] | [Why combine] |

**Join Types:**
- **INNER JOIN:** Only records that exist in both datasets
- **LEFT JOIN:** All records from left dataset, matched with right dataset (if available)
- **RIGHT JOIN:** All records from right dataset, matched with left dataset (if available)
- **FULL JOIN:** All records from both datasets

**Join Logic Examples:**
- `customer.id = order.customer_id AND order.date >= '2024-01-01'`
- `product.category = 'Electronics' AND sales.quantity > 10`
- `employee.department_id = department.id AND department.active = true`

## Analysis Methodology

### Analysis Approach
- **Analysis Type:** [Descriptive/Diagnostic/Predictive/Prescriptive]
- **Methodology:** [Which statistical method/technique]
- **Tools:** [Which tools/libraries will be used]
- **Key Assumptions:** [Key assumptions being made]

### Analysis Plan
| Step | Description | Dataset(s) | Output | Verification |
|------|-------------|-------------|--------|---------------|
| 1 | [Data preparation] | [Dataset] | [Cleaned data] | [Quality check] |
| 2 | [Data transformation/joining] | [Dataset] | [Combined data] | [Validation] |
| 3 | [Analysis execution] | [Dataset] | [Results] | [AC check] |
| 4 | [Result validation] | [Dataset] | [Validated results] | [AC check] |

### Key Considerations
- **Data Limitations:** [What limitations exist in the data]
- **Analysis Constraints:** [What constraints are there]
- **Critical Success Factors:** [What factors determine success]

## Visualization Plan (OPTIONAL)

> This section is only required if visualization is explicitly requested by the user.

### Visualization Strategy
- **Target Audience:** [Who will view this?]
- **Medium:** [Chart/Graph/Plot/etc.]

### Chart Type Selection
| Visualization | Chart Type | Data Source | Reason for Choice |
|---------------|-------------|-------------|-------------------|
| [Viz 1] | [Bar/Line/Scatter/etc.] | [Dataset] | [Why this type] |

## Deliverables

### Primary Deliverables
- [ ] Analyzed datasets
- [ ] Analysis results
- [ ] Conclusions and recommendations

### Optional Deliverables
- [ ] Visualizations (if requested)
- [ ] Technical documentation for reproducibility

## Builder Instructions

This section provides clear guidance for the data_builder agent to execute the analysis.

### Prerequisites
- All selected datasets are accessible and available
- Data join strategy is clearly defined (if multiple datasets)
- Analysis methodology is specified
- Acceptance criteria are defined

### Execution Steps
1. **Data Preparation**
   - Load selected datasets
   - Validate data structure and primary keys
   - Check data quality (completeness, accuracy, consistency)
   - Handle missing values and outliers according to methodology

2. **Data Integration** (if required)
   - Execute data joins according to join strategy table
   - Validate join results (record counts, key matching)
   - Handle join conflicts and null values
   - Create final combined dataset

3. **Analysis Execution**
   - Apply specified analysis methodology
   - Use selected tools/libraries
   - Generate analysis results
   - Document assumptions made during execution

4. **Validation**
   - Verify results against acceptance criteria
   - Check if success criteria are met
   - Validate business question is answered
   - Document any limitations or issues

5. **Deliverable Creation**
   - Prepare primary deliverables (analyzed datasets, results, conclusions)
   - Create optional visualizations (if requested)
   - Generate technical documentation for reproducibility

### Success Validation
The analysis is considered complete when:
- All acceptance criteria are validated
- The clarified question is satisfactorily answered
- Results are reproducible and documented
- Deliverables match the scope defined in this plan

### Error Handling
If any step fails:
1. Document the error and context
2. Identify if it's a data issue, join issue, or methodology issue
3. Attempt remediation based on methodology constraints
4. If unresolved, escalate with clear error description and impact on deliverables
