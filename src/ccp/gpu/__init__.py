"""Scripts that run inside cantocaptions-ai's venv (torch, CUDA, its models).

They are launched by ccp.gpu_bridge as `python src/ccp/gpu/<name>.py <request.json> <result.json>`
and may import only the standard library, numpy, torch, cantocaptions_ai and the pure
modules of ccp (srtio, groups, jyutping, paths, corpus constants).
"""
