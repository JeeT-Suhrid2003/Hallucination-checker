FROM nginx:alpine
COPY index.html index.html
CMD ["nginx", "-g", "daemon off;"]