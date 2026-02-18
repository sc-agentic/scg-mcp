# SCG MCP Tool – Test Questions for Glide Codebase

These questions are designed to evaluate an agentic system's ability to use the Semantic Code Graph (SCG) MCP tool for deep codebase comprehension. They are organized by the **type of software comprehension activity** that SCG is designed to support, following established SCG research.

The Glide codebase (v4.5.0) contains **17,685 nodes** and **67,292 edges**, with 667 classes, 3,704 methods, 118 traits (interfaces), and 549 constructors.

---

## Category 1: Project Structure Comprehension

These questions test the agent's ability to understand the overall organization and architecture.

**Q1.** What are the main packages (modules) in the Glide library, and what is each one responsible for?

**Q2.** How is the `com.bumptech.glide.load.engine` package structured? What are the key classes and how do they relate to each other?

---

## Category 2: Identification of Critical Entities

These questions test the ability to identify core components that are central to the system.

**Q3.** Which classes in the Glide codebase have the most incoming and outgoing relationships (edges)? What does this tell us about the architecture?

**Q4.** What is the role of the `Engine` class, and what are its direct dependencies?

---

## Category 3: Dependency Analysis & Data Flow

These questions test the ability to trace how data flows through the system and understand dependency chains.

**Q5.** Trace the complete image loading pipeline: what happens from the moment `Glide.with(context).load(url).into(imageView)` is called until the image is displayed? Which classes and methods are involved?

**Q6.** How does the `DecodeJob` interact with `DataFetcherGenerator` and `DecodePath`? Describe the data flow between these components.

---

## Category 4: Relationship Exploration (Inheritance & Implementation)

These questions test the ability to navigate inheritance hierarchies and interface implementations using graph relations.

**Q7.** What interface does `DataFetcherGenerator` define, and which classes implement it? How do these implementations differ in their role within the loading pipeline?

**Q8.** What is the class hierarchy of `Target` in Glide? List the inheritance chain and explain the purpose of each level.

---

## Category 5: Reachability & Impact Analysis

These questions test the ability to determine how changes in one part of the code could affect other parts.

**Q9.** If the `MemoryCache` interface were to change, which classes and components would be directly and indirectly affected?

**Q10.** What components depend on `DiskCacheStrategy`? How does changing the caching strategy propagate through the system?

---

## Category 6: Semantic Code Search & Cross-Cutting Concerns

These questions test the ability to use semantic search to find non-obvious code related to a concept.

**Q11.** How does Glide handle lifecycle management to prevent memory leaks? Which classes are involved in tying image requests to Android Activity/Fragment lifecycles?

**Q12.** Find all classes involved in bitmap recycling and pool management. How are they connected?

---

## Category 7: Software Quality & Architecture Assessment

These questions test the ability to use graph statistics and structural analysis to assess code quality.

**Q13.** Based on the graph statistics and entity distribution, what can you infer about the complexity of the Glide codebase? Are there any potential areas of concern (e.g., classes with too many dependencies)?

**Q14.** Analyze the relationship between `RequestBuilder`, `BaseRequestOptions`, and `RequestOptions`. Is there evidence of the Builder pattern, and how is it structured?

---

## Category 8: Multi-Hop Reasoning

These questions require the agent to traverse multiple relationship hops to build a complete picture.

**Q15.** Starting from the `GifDrawable` class, trace all its dependencies up to 3 hops. What subsystems of Glide does GIF support touch?

---

## Evaluation Criteria

For each question, the agentic system should be evaluated on:

| Criterion | Description |
|---|---|
| **Tool Usage** | Did the agent use appropriate SCG tools (search, context, source, stats)? |
| **Multi-Step Reasoning** | Did the agent chain multiple tool calls to build a complete answer? |
| **Accuracy** | Is the answer factually correct based on the codebase? |
| **Depth** | Did the agent go beyond surface-level answers to explain *why*? |
| **Efficiency** | Did the agent avoid unnecessary tool calls and find information efficiently? |
