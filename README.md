# Hallucination Checker

AI code tools are silently shipping ticking time bombs into Kubernetes production.

When developers "vibe-code" (*me) infrastructure, LLMs routinely hallucinate non-existent K8s keys, fabricate properties, and mix up syntax (e.g. leaking Docker properties into K8s specs). Standard linters don't catch these—so the API server crashes at runtime.

To solve this, I built an Autonomous AI Delivery Gateway that acts as an automated gatekeeper.

## What happens when code gets pushed

1. **The Hallucination Gate**: Uses Google Gemini (`gemini-3.5-flash-lite`) via the google-genai SDK to scan manifests against active schemas, catching hallucinated fields before anything deploys.

2. **Server-Side Dry-Run**: Executes `kubectl apply --dry-run=server` against a local Minikube cluster to guarantee runtime compatibility.

3. **Slack Alert & Auto-Remediation**: If it fails, it alerts the team on Slack via webhooks, triggers an AI self-healing loop, generates corrected YAML, and auto-opens a patch PR.

## Benchmarks & Engineering Takeaways

- **TinyLlama vs. Gemini**: I benchmarked local execution using a local SLM (TinyLlama via Ollama) to keep everything offline. While fast, local SLMs lacked the reasoning precision needed for strict YAML schema logic. Moving to Gemini's API yielded vastly superior, deterministic JSON validation.

- **The Money Trade-Off**: Minikube works great locally, but the ultimate setup is spinning up Ephemeral Clusters (via KinD or temporary cloud namespaces) dynamically on-demand for isolated PR testing—if you have the budget for it.

## Tech Stack

- GitHub Actions
- Minikube & (K3s)
- Google GenAI SDK
- Python 3.11
- Docker
- Slack Webhooks

## Execution Graph

Check out the execution graph below to see the gatekeeper in action.

![Execution graph](Screenshot%202026-08-10%20113146.png)


## Files of interest

- `checker.py` — core scanner and gate logic
- `deployment.yml` — example K8s manifest used for testing

## Links

Repository: https://github.com/JeeT-Suhrid2003/Hallucination-checker/tree/main


#DevOps #PlatformEngineering #Kubernetes #LLMOps #Docker #Python #SoftwareEngineering
