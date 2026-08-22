# Why this matters

*The longer argument for why I built a system that blocks its own output. Written as reasoning, not as a claim about what Maldros achieves. Nothing here is a result.*

---

There was a question I couldn't put down while I was researching this, and it kept me up more than the fraud numbers did. Everything I'd been looking at was operational. Stolen compute, abused API keys, accounts spun up to run scams. Expensive, but the kind of expensive a company absorbs and moves on from. Then I started reading about incidents where a model wasn't the thing being stolen from, it was the thing doing the work. Mapping a network, planning the intrusion path, writing the payloads, and deploying them against industrial control systems attached to physical infrastructure. Once that happens the category of risk changes completely. It stops being a line item and becomes the kind of event that ends an organisation in a single news cycle. And nobody in that aftermath is going to be looking for the person who typed the prompt. They're going to look at whoever's servers generated the code, and the question a court asks is not whether the attacker was clever. It's whether your safety controls were bypassed through negligence, and whether you exercised reasonable care. That's a much harder question to answer well after the fact than before it.

What actually convinced me this was structural rather than alarmist was the insurance side. Every other industry that builds something dangerous prices the catastrophe and buys coverage for it. Oil rigs, chemical plants, airlines. That works because there's decades of actuarial history to build a model from. For a system that can write a sonnet and a piece of malware in the same session, there is no history, so there's no model, so underwriters won't quote it. Which means the labs are self-insuring. They're holding capital against lawsuits that haven't been filed yet, for harms nobody has learned to price. When an entire industry can't buy a safety net, the safety net has to be engineered instead, and the thing being engineered isn't perfect prevention. Perfect prevention isn't achievable and anyone who's done security knows it. What you can build is a defensible record that you took care, and that record either exists at the moment you need it or it doesn't.

The lesson I took away is that this gets more serious, not less, as AI moves into the physical world. Infrastructure, manufacturing, robotics, vehicles. Anywhere a model's output turns into something that moves or something that fails. Software mistakes are recoverable and physical ones frequently aren't, and I think that's the real content of the argument that AI has to be deployed carefully rather than quickly. That's the reasoning that put me on the path to building what I built. If the binding constraint on deploying these systems turns out to be demonstrable evidence of care rather than raw capability, then an analytics system whose output is blocked unless every claim is sourced, whose governance decisions are all logged, and which refuses to act on anything consequential without a person signing for it, stops being a nice engineering habit. It becomes the thing you point at when someone asks what you did to prevent this.

---

## A note on sourcing

This is an argument, and I've written it as one. It rests on publicly reported incidents and on the general shape of the regulatory and insurance picture, not on original research of mine.

I've deliberately left out the specific figures I first drafted this with: settlement exposures, regulatory fines, artifact counts from particular intrusions. Some came to me second-hand through summaries of my own domain research, and at least one described a case whose subject matter turned out not to be what the surrounding argument implied. The argument doesn't depend on any of them, and a reader who checks one number and finds it doesn't mean what the sentence around it suggests will reasonably discount everything nearby. I'd rather the reasoning stand on its own than borrow weight from figures I can't personally vouch for.

The same standard applies here as everywhere else in this repository. Where I state a measured result, it comes from a recorded run and names the file it came from. Where I'm reasoning, as here, I say so.

---

← Back to the [README](../README.md) · The full argument for what was built is in the [case study](https://l-mota.github.io/maldros-analytics-system/case-study/).
