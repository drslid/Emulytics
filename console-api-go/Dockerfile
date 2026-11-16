FROM golang:1.27.4-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /console-api-go .

FROM alpine:3.23
RUN apk add --no-cache ca-certificates
COPY --from=build /console-api-go /console-api-go
USER 65532:65532
ENTRYPOINT ["/console-api-go"]
