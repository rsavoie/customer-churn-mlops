# Dataset canónico

## Fuente

- Nombre: **IBM Telco Customer Churn**
- Repositorio: <https://github.com/IBM/telco-customer-churn-on-icp4d>
- CSV crudo: <https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv>
- Licencia del repositorio fuente: Apache 2.0
- Manifiesto reproducible del caso: [`SOURCES.md`](SOURCES.md)

## Forma esperada

- Filas de datos: **7.043**
- Columnas: **21**
- Label: `Churn`
- Clase positiva: `Yes`
- Identificador excluido del entrenamiento: `customerID`
- SHA-256 local esperado: `16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91`

Columnas:

```text
customerID, gender, SeniorCitizen, Partner, Dependents, tenure,
PhoneService, MultipleLines, InternetService, OnlineSecurity,
OnlineBackup, DeviceProtection, TechSupport, StreamingTV,
StreamingMovies, Contract, PaperlessBilling, PaymentMethod,
MonthlyCharges, TotalCharges, Churn
```

## Uso en la materia

El dataset es un caso real de telecomunicaciones y calza directo con el Canvas de Churn:

- hay cliente y suscripción;
- hay señales de contrato, uso y facturación;
- es un corte transversal: una fila por cliente, sin historia mes a mes (en producción real habría fotos mensuales);
- hay una etiqueta binaria de abandono;
- permite explicar desbalance, umbrales, costo de falsos positivos y falsos negativos;
- permite traducir un score técnico a una acción de CRM.

Para el hilo 2026, `MonthlyCharges` funciona como aproximación sencilla de valor mensual. En una empresa real usaríamos revenue mensual, margen, LTV o valor esperado incremental.

## Verificación

```powershell
python scripts\verify_dataset.py
```

Salida esperada:

```text
OK dataset: 7043 filas, 21 columnas.
Churn Yes: 1869 | Churn No: 5174
SHA-256: 16320c9c1ec72448db59aa0a26a0b95401046bef5d02fd3aeb906448e3055e91
```
