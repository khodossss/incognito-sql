# syntax=docker/dockerfile:1.7
# dbmcp's published image (https://github.com/haymon-ai/dbmcp, MIT), release 0.15.2 pinned
# by digest, plus the NER model its docs recommend for the optional ML pass
# (docs/content/docs/configuration.mdx at tag v0.15.2, "ML/NER pass", "Set up a model locally"):
# optimum/bert-base-NER (MIT), an ONNX export of dslim/bert-base-NER, at a pinned revision,
# each file checked by its SHA-256. Nothing of either project's source is here.
FROM busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec AS model
ARG HF=https://huggingface.co/optimum/bert-base-NER/resolve/b0a40a015260b068fee8aaa46410f1b19943f435
ADD --checksum=sha256:fc396a890c253a2d48c8d93ad812bfaf9c58f12ded190d80e643e30e740b3e44 \
    ${HF}/config.json /models/bert-ner/config.json
ADD --checksum=sha256:343989712a36cd8b253efeaf8baf6a08b9d2583f78e395e83832e8ee9f8d8ee1 \
    ${HF}/tokenizer.json /models/bert-ner/tokenizer.json
ADD --checksum=sha256:f2ce2db27bafe29ab3052212ecdcc8fe438287963596008f235c2ff496e85ad3 \
    ${HF}/model.onnx /models/bert-ner/model.onnx

# The image runs as nonroot and ADD fetches owner-only files, so the tree is made readable.
RUN chmod 0755 /models /models/bert-ner && chmod 0444 /models/bert-ner/*

FROM ghcr.io/haymon-ai/dbmcp@sha256:2e3fbf09e1bea861b85909b4b46fcabb9234e854fb15df407b42c1a8cd8c0532
COPY --from=model /models /models
