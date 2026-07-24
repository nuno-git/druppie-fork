# @status active
# @superseded_by
# @adr
# @prd docs/prds/019-visualization-enhancements.md

# Spec (executable Gherkin) for Data Analyst chart improvements (PR #271).
#
# Traceability: the @prd tag links this behaviour back to PRD 019.

@prd docs/prds/019-visualization-enhancements.md
Feature: Data Analyst Chart Improvements
  # The "why" (problem, goal, user journey) lives in the linked PRD (@prd).
  # This spec holds only the acceptance Scenarios below.

  Scenario: Dataset with temporal data selects line chart sorted chronologically
    Given a dataset with a datetime column "order_date" and a numeric column "revenue"
    When the Data Analyst agent calls create_chart with auto chart type selection
    Then the chart type is "line"
    And the data is sorted chronologically by "order_date" ascending
    And the X axis shows the date values in order

  Scenario: Dataset with few categories selects pie chart
    Given a dataset with a categorical column "region" having 4 distinct values
    And a numeric column "sales"
    When the Data Analyst agent calls create_chart with auto chart type selection
    Then the chart type is "pie"
    And each slice represents one region
    And the slice sizes are proportional to the sales values

  Scenario: Dataset with long labels selects horizontal bar chart
    Given a dataset with a categorical column "product_name" containing labels longer than 20 characters
    And a numeric column "quantity"
    When the Data Analyst agent calls create_chart with auto chart type selection
    Then the chart type is "horizontal_bar"
    And the category labels are displayed on the Y axis
    And the bars extend horizontally from left to right

  Scenario: Dataset with many categories selects treemap
    Given a dataset with a categorical column "city" having 25 distinct values
    And a numeric column "population"
    When the Data Analyst agent calls create_chart with auto chart type selection
    Then the chart type is "treemap"
    And each city is rendered as a nested rectangle
    And the rectangle area is proportional to the population value

  Scenario: Dataset with multi-series data selects stacked bar or multi-line
    Given a dataset with a categorical column "quarter", a numeric column "revenue", and a series column "product_line"
    When the Data Analyst agent calls create_chart with auto chart type selection
    Then the chart type is "stacked_bar" or "multi_line"
    And each series is rendered as a distinct color
    And a legend maps colors to product_line values

  Scenario: Column name "total_revenue" is humanized to "Total Revenue"
    Given a dataset with a column named "total_revenue"
    When the Data Analyst agent generates chart labels
    Then the column label displays as "Total Revenue"

  Scenario: Column name "avg_temperature" is humanized to "Average Temperature"
    Given a dataset with a column named "avg_temperature"
    When the Data Analyst agent generates chart labels
    Then the column label displays as "Average Temperature"

  Scenario: Pie chart with many slices has readable margin and legend
    Given a pie chart with 12 slices
    When the chart is rendered
    Then the chart has a margin of at least 20px on each side
    And a legend is displayed to the right of the chart
    And each legend entry shows the slice label and its value

  Scenario: X axis with more than 20 data points applies interval
    Given a line chart with 35 data points on the X axis
    When the chart is rendered
    Then the X axis labels show an interval of at least 5
    And labels are not overlapping
    And all data points are still plotted

  Scenario: Treemap cells have correct fill color
    Given a treemap chart with 3 categories
    When the chart is rendered
    Then each cell has a fill color other than "none"
    And cells in the same category share the same fill color

  Scenario: Chart title is auto-generated from dataset context
    Given a dataset with columns "region" and "sales"
    And the user query is "Show me sales by region"
    When the Data Analyst agent generates the chart
    Then the chart title is "Sales by Region"
    And the title is displayed above the chart
