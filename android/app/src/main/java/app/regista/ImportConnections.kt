package app.regista

import android.os.SystemClock
import java.io.IOException
import java.net.Inet4Address
import java.net.NetworkInterface
import javax.net.ssl.HttpsURLConnection

data class ImportConnection(val computer:Computer,val transport:String)

class ImportConnections(private val memory:Memory,private val changed:(HttpsURLConnection?)->Unit,private val cancelled:()->Boolean) {
    private var advertised=emptyList<String>()
    private var searchedUsb=0L
    private var searchedNetwork=0L
    private fun subnets()=NetworkInterface.getNetworkInterfaces().toList()
        .filter { it.isUp && !it.isLoopback && BackupNetwork.localInterface(it.name) }
        .flatMap { nic -> nic.interfaceAddresses.filter { it.address is Inet4Address }
            .mapNotNull { own -> own.address.hostAddress?.takeIf(::isPrivate)?.let { ImportSubnet(nic.name,it,own.networkPrefixLength.toInt()) } } }

    private fun hello(address:String,routes:List<ImportSubnet>):ImportConnection? {
        if (cancelled()) throw java.util.concurrent.CancellationException()
        val computer=memory.ways(listOf(address)).first()
        try {
            val response=computer.ask("GET","/phone/hello",connectionChanged=changed)
            if (response.optInt("import_protocol")!=2) throw Refused(426,"Aggiorna Regista sul PC per importare insieme foto e video.")
            response.optJSONArray("addresses")?.let { list -> advertised=(0 until list.length()).map { list.getString(it) }.filter(::isPrivate) }
            memory.worked(address)
            return ImportConnection(computer,TransferRouting.transport(address,routes))
        } catch (error:Refused) { throw error }
        catch (_:IOException) { return null }
    }

    fun choose(usbOnly:Boolean=false):ImportConnection? {
        val routes=subnets()
        val known=TransferRouting.order(memory.addresses+advertised,routes)
        val usb=routes.filter { TransferRouting.usb(it.name) }
        for (address in known.filter { TransferRouting.transport(it,routes)=="usb" }) hello(address,routes)?.let { return it }
        val now=SystemClock.elapsedRealtime()
        if (usb.isNotEmpty() && (searchedUsb==0L || now-searchedUsb>30_000)) {
            searchedUsb=now
            val peers=usb.flatMap { own -> (1..254).map { "${own.address.substringBeforeLast('.')}.$it" }
                .filter { it!=own.address && TransferRouting.contains(own,it) && it !in known } }.distinct()
            for (address in listening(peers,memory.port)) hello(address,routes)?.let { return it }
        }
        if (usbOnly) return null
        for (address in known.filter { TransferRouting.transport(it,routes)!="usb" }) hello(address,routes)?.let { return it }
        if (searchedNetwork==0L || now-searchedNetwork>60_000) {
            searchedNetwork=now
            for (address in listening(neighbours().filter { it !in known },memory.port)) hello(address,routes)?.let { return it }
        }
        return null
    }
}
