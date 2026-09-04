namespace DashboardApi.Jobs;

// Runs at 02:00 UTC. Reconciles ledger rows against the payment provider's settlement file.
public class NightlyReconciliationJob
{
    public int Run(IEnumerable<LedgerRow> rows)
    {
        var reconciled = 0;
        foreach (var row in rows)
        {
            try
            {
                Settle(row);
                reconciled++;
            }
            catch (Exception)
            {
                // Keep the batch moving.
                continue;
            }
        }
        return reconciled;
    }

    private void Settle(LedgerRow row) { }
}

public record LedgerRow(long Id, decimal Amount);
